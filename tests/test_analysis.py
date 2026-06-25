"""Tests for Stage 1 — AnalysisStage and supporting functions.

LLM calls are mocked; these tests cover text extraction, chunking, merging,
graph persistence, and cache invalidation without any network traffic.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from colophon.config import LLMConfig, OutputConfig, PipelineConfig
from colophon.stages.analysis import (
    AnalysisStage,
    _analyze_chunks,
    _build_graph,
    _build_graph_batch,
    _chunk_spine,
    _extract_spine_texts,
    _is_pollution,
    _merge_into,
    _reconcile_characters,
    _resolve_graph_path,
    _sha256,
    empty_graph,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_epub(tmp_path: Path, spine_texts: dict[str, str]) -> Path:
    """Build a minimal EPUB 2 ZIP with the given spine items."""
    epub_path = tmp_path / "test.epub"
    oebps = tmp_path / "oebps_src"
    oebps.mkdir()

    manifest_items = ""
    spine_items = ""
    for i, (name, text) in enumerate(spine_texts.items()):
        (oebps / name).write_text(
            f"<html><body><p>{text}</p></body></html>", encoding="utf-8"
        )
        manifest_items += f'<item id="i{i}" href="{name}" media-type="application/xhtml+xml"/>\n'
        spine_items += f'<itemref idref="i{i}"/>\n'

    opf = f"""<?xml version="1.0"?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test Book</dc:title>
    <dc:identifier id="uid">test-001</dc:identifier>
  </metadata>
  <manifest>{manifest_items}</manifest>
  <spine>{spine_items}</spine>
</package>"""
    (oebps / "content.opf").write_text(opf, encoding="utf-8")

    container = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="oebps_src/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")
        zf.writestr("META-INF/container.xml", container)
        for name in spine_texts:
            zf.write(oebps / name, f"oebps_src/{name}")
        zf.write(oebps / "content.opf", "oebps_src/content.opf")

    return epub_path


def _extract_epub(epub_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(epub_path) as zf:
        zf.extractall(dest)


# ---------------------------------------------------------------------------
# _chunk_spine
# ---------------------------------------------------------------------------

def test_chunk_spine_single_chunk():
    items = [{"href": "a.html", "text": "hello world"}]
    chunks = _chunk_spine(items, max_chars=10000)
    assert len(chunks) == 1
    assert "hello world" in chunks[0]["text"]


def test_chunk_spine_splits_on_overflow():
    items = [
        {"href": "a.html", "text": "A" * 500},
        {"href": "b.html", "text": "B" * 500},
    ]
    chunks = _chunk_spine(items, max_chars=600)
    assert len(chunks) == 2


def test_chunk_spine_splits_oversized_item_without_loss():
    """A spine item larger than max_chars must be split across chunks, not
    truncated — every paragraph has to survive."""
    paras = [f"Paragraph {i} mentions Character{i}." for i in range(200)]
    items = [{"href": "a.html", "text": "\n\n".join(paras)}]
    chunks = _chunk_spine(items, max_chars=500)

    assert len(chunks) > 1
    assert all(len(c["text"]) <= 500 for c in chunks)
    combined = "\n".join(c["text"] for c in chunks)
    # No content dropped: first, middle, and last paragraphs all present.
    assert "Character0." in combined
    assert "Character99." in combined
    assert "Character199." in combined


def test_chunk_spine_hard_splits_single_huge_paragraph():
    """A single paragraph longer than max_chars is hard-split, not dropped."""
    items = [{"href": "a.html", "text": "X" * 2000}]
    chunks = _chunk_spine(items, max_chars=500)
    assert all(len(c["text"]) <= 500 for c in chunks)
    assert sum(c["text"].count("X") for c in chunks) == 2000


# ---------------------------------------------------------------------------
# _merge_into
# ---------------------------------------------------------------------------

def _chars(*entities):
    return {"characters": list(entities), "places": [], "organizations": [],
            "invented_terms": [], "chapters": []}


def test_merge_sums_occurrences():
    graph = empty_graph("abc", "test/model")
    partials = [
        _chars({"canonical": "Kirk", "variants": [], "occurrences": 5}),
        _chars({"canonical": "Kirk", "variants": ["James Kirk"], "occurrences": 3}),
    ]
    _merge_into(graph, partials)
    chars = graph["entities"]["characters"]
    assert len(chars) == 1
    assert chars[0]["canonical"] == "Kirk"
    assert chars[0]["occurrences"] == 8
    assert "James Kirk" in chars[0]["variants"]


def test_merge_clusters_distinct_canonicals_of_same_entity():
    """The regression that motivated the rewrite: five surface forms of Kirk
    chosen as canonical by different chunks must collapse to ONE character."""
    graph = empty_graph("abc", "test/model")
    partials = [
        _chars({"canonical": "Kirk", "variants": ["Jim", "James T. Kirk"], "occurrences": 252}),
        _chars({"canonical": "Jim Kirk", "variants": ["Kirk", "Captain Kirk"], "occurrences": 227}),
        _chars({"canonical": "James T. Kirk", "variants": ["Kirk", "Jim"], "occurrences": 133}),
        _chars({"canonical": "James Kirk", "variants": ["Kirk"], "occurrences": 61}),
    ]
    _merge_into(graph, partials)
    chars = graph["entities"]["characters"]
    assert len(chars) == 1, f"Expected 1 Kirk, got {[c['canonical'] for c in chars]}"
    assert chars[0]["canonical"] == "Kirk"          # most frequent surface form
    assert chars[0]["occurrences"] == 252 + 227 + 133 + 61
    assert "James T. Kirk" in chars[0]["variants"]
    assert "Jim Kirk" in chars[0]["variants"]


def test_merge_does_not_overcluster_distinct_entities():
    """Two full names sharing a surname are distinct people and must stay
    separate; a bare "Kirk" is ambiguous between them and is also left alone."""
    graph = empty_graph("abc", "test/model")
    partials = [
        _chars(
            {"canonical": "James Kirk", "variants": ["Jim"], "occurrences": 200},
            {"canonical": "George Kirk", "variants": ["George", "Jim's father"], "occurrences": 3},
            {"canonical": "Kirk", "variants": [], "occurrences": 50},
        ),
    ]
    _merge_into(graph, partials)
    names = {c["canonical"] for c in graph["entities"]["characters"]}
    assert names == {"James Kirk", "George Kirk", "Kirk"}


def test_merge_links_title_surname_to_full_name():
    """"Mr. Foster" and "Henry Foster" are the same person and must merge,
    even though neither lists the other as a surface form."""
    graph = empty_graph("abc", "test/model")
    partials = [
        _chars(
            {"canonical": "Mr. Foster", "variants": ["Foster"], "occurrences": 17},
            {"canonical": "Henry Foster", "variants": ["Henry"], "occurrences": 4},
        ),
    ]
    _merge_into(graph, partials)
    chars = graph["entities"]["characters"]
    assert len(chars) == 1, f"Expected 1 Foster, got {[c['canonical'] for c in chars]}"
    assert chars[0]["occurrences"] == 21
    surfaces = {chars[0]["canonical"], *chars[0]["variants"]}
    assert {"Mr. Foster", "Henry Foster", "Henry", "Foster"} <= surfaces


def test_merge_links_rank_surname_to_full_name():
    """Ranks count as titles: "Captain Kirk" → "James Kirk"."""
    graph = empty_graph("abc", "test/model")
    partials = [
        _chars(
            {"canonical": "Captain Kirk", "variants": [], "occurrences": 5},
            {"canonical": "James Kirk", "variants": [], "occurrences": 9},
        ),
    ]
    _merge_into(graph, partials)
    assert len(graph["entities"]["characters"]) == 1


def test_merge_links_bare_surname_when_surname_is_unique():
    """A bare surname merges into the full name when only one person has that
    surname — there's no one else it could refer to."""
    graph = empty_graph("abc", "test/model")
    partials = [
        _chars(
            {"canonical": "Foster", "variants": [], "occurrences": 10},
            {"canonical": "Henry Foster", "variants": [], "occurrences": 4},
        ),
    ]
    _merge_into(graph, partials)
    chars = graph["entities"]["characters"]
    assert len(chars) == 1
    assert chars[0]["occurrences"] == 14


def test_merge_does_not_link_bare_surname_when_ambiguous():
    """A bare surname shared by two full names stays separate (ambiguous)."""
    graph = empty_graph("abc", "test/model")
    partials = [
        _chars(
            {"canonical": "Foster", "variants": [], "occurrences": 10},
            {"canonical": "Henry Foster", "variants": [], "occurrences": 4},
            {"canonical": "Jack Foster", "variants": [], "occurrences": 3},
        ),
    ]
    _merge_into(graph, partials)
    names = {c["canonical"] for c in graph["entities"]["characters"]}
    assert names == {"Foster", "Henry Foster", "Jack Foster"}


def test_merge_does_not_link_mr_and_mrs():
    """Different honorifics on the same surname are different people."""
    graph = empty_graph("abc", "test/model")
    partials = [
        _chars(
            {"canonical": "Mr. Foster", "variants": [], "occurrences": 10},
            {"canonical": "Mrs. Foster", "variants": [], "occurrences": 8},
        ),
    ]
    _merge_into(graph, partials)
    names = {c["canonical"] for c in graph["entities"]["characters"]}
    assert names == {"Mr. Foster", "Mrs. Foster"}


def test_merge_title_surname_only_applies_to_characters():
    """The personal-name rule must not touch places/orgs — "York" is not
    "New York"."""
    graph = empty_graph("abc", "test/model")
    partials = [
        {"characters": [], "organizations": [], "invented_terms": [], "chapters": [],
         "places": [
            {"canonical": "Dr. York", "variants": [], "occurrences": 3},
            {"canonical": "New York", "variants": [], "occurrences": 5},
         ]},
    ]
    _merge_into(graph, partials)
    names = {p["canonical"] for p in graph["entities"]["places"]}
    assert names == {"Dr. York", "New York"}


def test_merge_blocks_cross_gender_attach():
    """"Mrs. Weston" must not merge into the male "George Weston" — they are
    two different people who share a surname."""
    graph = empty_graph("abc", "test/model")
    partials = [
        _chars(
            {"canonical": "Mrs. Weston", "variants": ["Grace"], "gender": "female",
             "occurrences": 28},
            {"canonical": "George Weston", "variants": [], "gender": "male",
             "occurrences": 12},
        ),
    ]
    _merge_into(graph, partials)
    names = {c["canonical"] for c in graph["entities"]["characters"]}
    assert names == {"Mrs. Weston", "George Weston"}


def test_merge_attaches_when_gender_unknown():
    """Sci-fi / invented names without a gender cue fall back to the
    surname-uniqueness rule and still merge."""
    graph = empty_graph("abc", "test/model")
    partials = [
        _chars(
            {"canonical": "Vorn", "variants": [], "gender": "unknown", "occurrences": 5},
            {"canonical": "Zyl Vorn", "variants": [], "gender": "unknown", "occurrences": 9},
        ),
    ]
    _merge_into(graph, partials)
    assert len(graph["entities"]["characters"]) == 1


def test_merge_emits_gender_for_characters():
    graph = empty_graph("abc", "test/model")
    partials = [
        _chars({"canonical": "Henry Foster", "variants": [], "gender": "male",
                "occurrences": 4}),
    ]
    _merge_into(graph, partials)
    assert graph["entities"]["characters"][0]["gender"] == "male"


def test_pollution_filter_drops_pronouns_and_descriptions():
    assert _is_pollution("he", "characters")
    assert _is_pollution("She", "characters")
    assert _is_pollution("the robot", "characters")
    assert _is_pollution("a man", "characters")
    assert _is_pollution("his father", "characters")
    assert _is_pollution("robot", "characters")          # bare lowercase noun
    # Real names and designations survive.
    assert not _is_pollution("Henry Foster", "characters")
    assert not _is_pollution("RB-34", "characters")
    assert not _is_pollution("QT-1", "characters")
    # Invented terms keep legitimately-lowercase names.
    assert not _is_pollution("soma", "invented_terms")
    assert _is_pollution("it", "invented_terms")         # pronouns dropped everywhere


def test_merge_strips_polluted_variants():
    """Pronouns and descriptions the LLM dumps into variants are removed."""
    graph = empty_graph("abc", "test/model")
    partials = [
        _chars({
            "canonical": "Susan Calvin",
            "variants": ["Calvin", "Dr. Calvin", "she", "the lady", "psychologist"],
            "gender": "female",
            "occurrences": 200,
        }),
    ]
    _merge_into(graph, partials)
    variants = set(graph["entities"]["characters"][0]["variants"])
    assert "Calvin" in variants
    assert "Dr. Calvin" in variants
    assert {"she", "the lady", "psychologist"} & variants == set()


# ---------------------------------------------------------------------------
# Reconciliation pass (_reconcile_characters)
# ---------------------------------------------------------------------------

class _ReconcileAdapter:
    """Fake adapter returning a canned reconciliation result."""

    def __init__(self, groups=None, raises=False):
        self._groups = groups or []
        self._raises = raises

    def complete_json(self, system, user):
        if self._raises:
            raise RuntimeError("model exploded")
        return {"groups": self._groups}


def _char(canonical, gender="unknown", occ=1, variants=None):
    return {"canonical": canonical, "variants": variants or [], "gender": gender, "occurrences": occ}


def test_reconcile_merges_high_confidence_no_shared_substring():
    chars = [
        _char("Pierre", "male", 200), _char("Bezukhov", "male", 80),
        _char("Pyotr Kirillovich", "male", 30), _char("Helene", "female", 50),
    ]
    groups = [{"members": ["Pierre", "Bezukhov", "Pyotr Kirillovich"],
               "canonical": "Pierre Bezukhov", "confidence": "high", "reason": "same man"}]
    out, flags = _reconcile_characters(_ReconcileAdapter(groups), chars)
    names = {c["canonical"] for c in out}
    assert names == {"Pierre Bezukhov", "Helene"}
    pierre = next(c for c in out if c["canonical"] == "Pierre Bezukhov")
    assert pierre["occurrences"] == 310
    assert pierre["reconciled"] is True
    assert {"Pierre", "Bezukhov", "Pyotr Kirillovich"} <= set(pierre["variants"])
    assert flags == []


def test_reconcile_flags_low_confidence_without_merging():
    chars = [_char("Strider", "male", 40), _char("Aragorn", "male", 60)]
    groups = [{"members": ["Strider", "Aragorn"], "canonical": "Aragorn",
               "confidence": "medium", "reason": "maybe"}]
    out, flags = _reconcile_characters(_ReconcileAdapter(groups), chars)
    assert {c["canonical"] for c in out} == {"Strider", "Aragorn"}  # not merged
    assert len(flags) == 1 and flags[0]["confidence"] == "medium"


def test_reconcile_rejects_cross_gender_merge():
    chars = [_char("Mr. Weston", "male", 30), _char("Mrs. Weston", "female", 28)]
    groups = [{"members": ["Mr. Weston", "Mrs. Weston"], "canonical": "Weston",
               "confidence": "high", "reason": "same surname"}]
    out, flags = _reconcile_characters(_ReconcileAdapter(groups), chars)
    assert {c["canonical"] for c in out} == {"Mr. Weston", "Mrs. Weston"}  # stays split
    assert flags and "REJECTED" in flags[0]["reason"]


def test_reconcile_ignores_unknown_members():
    chars = [_char("Kirk", "male", 100), _char("Spock", "male", 90)]
    groups = [{"members": ["Kirk", "Khan"], "canonical": "Kirk", "confidence": "high"}]
    out, _ = _reconcile_characters(_ReconcileAdapter(groups), chars)
    assert {c["canonical"] for c in out} == {"Kirk", "Spock"}  # only 1 real member -> no-op


def test_reconcile_survives_llm_failure():
    chars = [_char("Kirk", "male", 100), _char("Spock", "male", 90)]
    out, flags = _reconcile_characters(_ReconcileAdapter(raises=True), chars)
    assert out == chars and flags == []


def test_merge_deduplicates_chapters():
    graph = empty_graph("abc", "test/model")
    chapter = {"index": 0, "title": "Chapter 1", "spine_item": "a.html", "first_line": "It was"}
    partials = [
        {"characters": [], "places": [], "organizations": [], "invented_terms": [],
         "chapters": [dict(chapter)]},
        {"characters": [], "places": [], "organizations": [], "invented_terms": [],
         "chapters": [dict(chapter)]},
    ]
    _merge_into(graph, partials)
    assert len(graph["chapters"]) == 1


def test_merge_sorts_by_occurrence():
    graph = empty_graph("abc", "test/model")
    partials = [
        _chars(
            {"canonical": "Spock", "variants": [], "occurrences": 2},
            {"canonical": "Kirk", "variants": [], "occurrences": 10},
        ),
    ]
    _merge_into(graph, partials)
    assert graph["entities"]["characters"][0]["canonical"] == "Kirk"


def test_merge_tolerates_bad_occurrence_values():
    graph = empty_graph("abc", "test/model")
    partials = [
        _chars({"canonical": "Kirk", "variants": [], "occurrences": "lots"}),
        _chars({"canonical": "Kirk", "variants": [], "occurrences": None}),
    ]
    _merge_into(graph, partials)
    assert graph["entities"]["characters"][0]["occurrences"] == 0


# ---------------------------------------------------------------------------
# _resolve_graph_path
# ---------------------------------------------------------------------------

def test_resolve_graph_path_default(tmp_path):
    epub = tmp_path / "mybook.epub"
    cfg = PipelineConfig()
    assert _resolve_graph_path(epub, cfg) == tmp_path / "mybook.colophon.json"


def test_resolve_graph_path_explicit(tmp_path):
    epub = tmp_path / "mybook.epub"
    cfg = PipelineConfig()
    cfg.output.graph_output_path = tmp_path / "custom.json"
    assert _resolve_graph_path(epub, cfg) == tmp_path / "custom.json"


# ---------------------------------------------------------------------------
# AnalysisStage — full run with mocked LLM
# ---------------------------------------------------------------------------

MOCK_RESPONSE = {
    "characters": [{"canonical": "Kirk", "variants": ["James Kirk"], "occurrences": 12}],
    "places": [{"canonical": "Enterprise", "variants": [], "occurrences": 8}],
    "organizations": [],
    "invented_terms": [{"canonical": "Starfleet", "variants": [], "occurrences": 5}],
    "chapters": [{"index": 0, "title": "Chapter 1", "spine_item": "ch1.html", "first_line": "Captain's log"}],
}


def test_analysis_stage_writes_graph(tmp_path):
    epub = _make_epub(tmp_path, {"ch1.html": "Captain Kirk boarded the Enterprise. Kirk spoke."})
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _extract_epub(epub, work_dir)

    cfg = PipelineConfig()

    with patch("colophon.stages.analysis.LLMAdapter") as MockAdapter:
        MockAdapter.return_value.complete_json.return_value = MOCK_RESPONSE
        stage = AnalysisStage()
        ctx: dict = {"epub_path": epub, "config": cfg, "work_dir": work_dir}
        stage.run(ctx)

    assert "book_graph" in ctx
    graph_path = epub.with_suffix(".colophon.json")
    assert graph_path.exists()
    graph = json.loads(graph_path.read_text())
    assert graph["entities"]["characters"][0]["canonical"] == "Kirk"


def test_analysis_stage_uses_cache(tmp_path):
    epub = _make_epub(tmp_path, {"ch1.html": "Kirk."})
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _extract_epub(epub, work_dir)

    cfg = PipelineConfig()

    sha = _sha256(epub)
    # Cache hit requires the stored model to match the configured model.
    cached = empty_graph(sha, cfg.llm.model)
    cached["entities"]["characters"] = [{"canonical": "CachedKirk", "variants": [], "occurrences": 1}]
    graph_path = epub.with_suffix(".colophon.json")
    graph_path.write_text(json.dumps(cached), encoding="utf-8")

    with patch("colophon.stages.analysis.LLMAdapter") as MockAdapter:
        stage = AnalysisStage()
        ctx: dict = {"epub_path": epub, "config": cfg, "work_dir": work_dir}
        stage.run(ctx)
        MockAdapter.return_value.complete_json.assert_not_called()

    assert ctx["book_graph"]["entities"]["characters"][0]["canonical"] == "CachedKirk"


def test_analysis_stage_rebuilds_when_model_differs(tmp_path):
    """A cached graph built by a different model must not be reused."""
    epub = _make_epub(tmp_path, {"ch1.html": "Kirk."})
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _extract_epub(epub, work_dir)

    sha = _sha256(epub)
    cached = empty_graph(sha, "some-other/model")
    cached["entities"]["characters"] = [{"canonical": "CachedKirk", "variants": [], "occurrences": 1}]
    graph_path = epub.with_suffix(".colophon.json")
    graph_path.write_text(json.dumps(cached), encoding="utf-8")

    cfg = PipelineConfig()  # default model differs from the stored "some-other/model"

    with patch("colophon.stages.analysis.LLMAdapter") as MockAdapter:
        MockAdapter.return_value.complete_json.return_value = MOCK_RESPONSE
        stage = AnalysisStage()
        ctx: dict = {"epub_path": epub, "config": cfg, "work_dir": work_dir}
        stage.run(ctx)
        MockAdapter.return_value.complete_json.assert_called()


def test_analysis_stage_rebuild_graph_ignores_cache(tmp_path):
    epub = _make_epub(tmp_path, {"ch1.html": "Kirk."})
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _extract_epub(epub, work_dir)

    sha = _sha256(epub)
    cached = empty_graph(sha, "cached/model")
    graph_path = epub.with_suffix(".colophon.json")
    graph_path.write_text(json.dumps(cached), encoding="utf-8")

    cfg = PipelineConfig(rebuild_graph=True)

    with patch("colophon.stages.analysis.LLMAdapter") as MockAdapter:
        MockAdapter.return_value.complete_json.return_value = MOCK_RESPONSE
        stage = AnalysisStage()
        ctx: dict = {"epub_path": epub, "config": cfg, "work_dir": work_dir}
        stage.run(ctx)
        MockAdapter.return_value.complete_json.assert_called()


def test_analysis_stage_no_persist(tmp_path):
    epub = _make_epub(tmp_path, {"ch1.html": "Kirk."})
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _extract_epub(epub, work_dir)

    cfg = PipelineConfig()
    cfg.output.persist_graph = False

    with patch("colophon.stages.analysis.LLMAdapter") as MockAdapter:
        MockAdapter.return_value.complete_json.return_value = MOCK_RESPONSE
        stage = AnalysisStage()
        ctx: dict = {"epub_path": epub, "config": cfg, "work_dir": work_dir}
        stage.run(ctx)

    assert not epub.with_suffix(".colophon.json").exists()


# ---------------------------------------------------------------------------
# Concurrency (_analyze_chunks)
# ---------------------------------------------------------------------------

class _OrderProbeAdapter:
    """Fake adapter that tags each response with its chunk number and sleeps
    so that earlier chunks finish *last* — exposing any ordering bug."""

    def __init__(self, fail_on: set[int] | None = None):
        self._fail_on = fail_on or set()

    def complete_json(self, system: str, user: str):
        import re
        import time

        idx = int(re.search(r"chunk (\d+)/", user).group(1))
        if idx in self._fail_on:
            raise ValueError("simulated non-JSON response")
        time.sleep(0.02 * (10 - idx))  # invert completion order vs. chunk order
        return {"characters": [{"canonical": f"C{idx}", "variants": [], "occurrences": 1}]}


def test_analyze_chunks_preserves_order_under_concurrency():
    chunks = [{"text": f"t{i}", "hrefs": []} for i in range(4)]
    partials = _analyze_chunks(_OrderProbeAdapter(), chunks, max_concurrency=4)
    assert [p["characters"][0]["canonical"] for p in partials] == ["C1", "C2", "C3", "C4"]


def test_analyze_chunks_drops_failures_keeps_order():
    chunks = [{"text": f"t{i}", "hrefs": []} for i in range(4)]
    partials = _analyze_chunks(_OrderProbeAdapter(fail_on={2}), chunks, max_concurrency=4)
    assert [p["characters"][0]["canonical"] for p in partials] == ["C1", "C3", "C4"]


def test_analyze_chunks_single_worker_is_sequential():
    chunks = [{"text": f"t{i}", "hrefs": []} for i in range(3)]
    partials = _analyze_chunks(_OrderProbeAdapter(), chunks, max_concurrency=1)
    assert [p["characters"][0]["canonical"] for p in partials] == ["C1", "C2", "C3"]


# ---------------------------------------------------------------------------
# OpenAI Batch API path
# ---------------------------------------------------------------------------

def _make_batch_result_line(custom_id: str, content: str) -> str:
    """Build a single JSONL line in OpenAI Batch API result format."""
    import json
    return json.dumps({
        "custom_id": custom_id,
        "response": {
            "status_code": 200,
            "body": {
                "choices": [{"message": {"content": content}}],
            },
        },
        "error": None,
    })


_BATCH_NER_RESPONSE = json.dumps({
    "characters": [{"canonical": "Spock", "variants": ["Mr. Spock"], "occurrences": 7}],
    "places": [],
    "organizations": [],
    "invented_terms": [],
    "chapters": [],
})


def _mock_openai_client(completed_status: str = "completed") -> MagicMock:
    """Build a fully wired mock OpenAI client for Batch API calls."""
    client = MagicMock()

    # files.create → file object with .id
    mock_file = MagicMock()
    mock_file.id = "file-input-123"
    client.files.create.return_value = mock_file

    # batches.create → in_progress batch
    mock_batch_in_progress = MagicMock()
    mock_batch_in_progress.id = "batch-abc"
    mock_batch_in_progress.status = "in_progress"

    # batches.retrieve → completed batch
    mock_batch_done = MagicMock()
    mock_batch_done.id = "batch-abc"
    mock_batch_done.status = completed_status
    mock_batch_done.output_file_id = "file-output-456"

    client.batches.create.return_value = mock_batch_in_progress
    client.batches.retrieve.return_value = mock_batch_done

    # files.content → JSONL result text (one line per chunk)
    mock_content = MagicMock()
    mock_content.text = _make_batch_result_line("chunk-0", _BATCH_NER_RESPONSE)
    client.files.content.return_value = mock_content

    return client


def test_batch_mode_submits_and_parses(tmp_path):
    """Batch path: successful completion → partial graphs returned."""
    cfg = PipelineConfig()
    cfg.llm.model = "openai/gpt-5.4-mini"
    cfg.llm.use_batch = True
    cfg.llm.batch_poll_interval = 0   # no sleeping in tests
    cfg.llm.batch_timeout = 3600

    chunks = [{"text": "Spock entered the bridge.", "hrefs": ["ch1.xhtml"]}]

    mock_client = _mock_openai_client()

    with patch("openai.OpenAI", return_value=mock_client):
        partials = _build_graph_batch(cfg, chunks)

    assert partials is not None
    assert len(partials) == 1
    assert partials[0]["characters"][0]["canonical"] == "Spock"

    # Verify the batch API sequence was called correctly
    mock_client.files.create.assert_called_once()
    mock_client.batches.create.assert_called_once()
    mock_client.batches.retrieve.assert_called_once()   # polled once → completed
    mock_client.files.content.assert_called_once_with("file-output-456")


def test_batch_mode_jsonl_content(tmp_path):
    """The uploaded JSONL must contain one valid request per chunk."""
    cfg = PipelineConfig()
    cfg.llm.model = "openai/gpt-5.4-nano"
    cfg.llm.use_batch = True
    cfg.llm.batch_poll_interval = 0
    cfg.llm.batch_timeout = 3600

    chunks = [
        {"text": "Chunk one text.", "hrefs": ["ch1.xhtml"]},
        {"text": "Chunk two text.", "hrefs": ["ch2.xhtml"]},
    ]

    captured_jsonl: list[str] = []

    mock_client = _mock_openai_client()

    def capturing_create(**kwargs):
        captured_jsonl.append(kwargs["file"][1].read().decode())
        mock_file = MagicMock()
        mock_file.id = "file-input-123"
        return mock_file

    mock_client.files.create.side_effect = capturing_create

    # Two-chunk result
    mock_client.files.content.return_value.text = "\n".join([
        _make_batch_result_line("chunk-0", _BATCH_NER_RESPONSE),
        _make_batch_result_line("chunk-1", _BATCH_NER_RESPONSE),
    ])

    with patch("openai.OpenAI", return_value=mock_client):
        partials = _build_graph_batch(cfg, chunks)

    assert len(partials) == 2

    # Inspect the uploaded JSONL
    lines = [l for l in captured_jsonl[0].splitlines() if l.strip()]
    assert len(lines) == 2
    req0 = json.loads(lines[0])
    assert req0["custom_id"] == "chunk-0"
    assert req0["body"]["model"] == "gpt-5.4-nano"   # prefix stripped


def test_batch_mode_failed_batch_returns_empty(tmp_path):
    """If the batch fails/expires, return an empty list (don't crash)."""
    cfg = PipelineConfig()
    cfg.llm.model = "openai/gpt-5.4-mini"
    cfg.llm.use_batch = True
    cfg.llm.batch_poll_interval = 0
    cfg.llm.batch_timeout = 3600

    chunks = [{"text": "Some text.", "hrefs": ["ch1.xhtml"]}]
    mock_client = _mock_openai_client(completed_status="failed")

    with patch("openai.OpenAI", return_value=mock_client):
        partials = _build_graph_batch(cfg, chunks)

    assert partials == []


def test_batch_mode_ignored_for_non_openai(tmp_path):
    """use_batch is silently ignored when the model is not openai/*."""
    epub = _make_epub(tmp_path, {"ch1.html": "Kirk."})
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _extract_epub(epub, work_dir)

    cfg = PipelineConfig()
    cfg.llm.model = "anthropic/claude-haiku-4-5"
    cfg.llm.use_batch = True   # should be ignored — model is anthropic/

    with patch("colophon.stages.analysis.LLMAdapter") as MockAdapter:
        MockAdapter.return_value.complete_json.return_value = MOCK_RESPONSE
        with patch("colophon.stages.analysis._build_graph_batch") as mock_batch:
            stage = AnalysisStage()
            ctx: dict = {"epub_path": epub, "config": cfg, "work_dir": work_dir}
            stage.run(ctx)
            mock_batch.assert_not_called()   # batch path never entered
