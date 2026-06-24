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
    _build_graph,
    _chunk_spine,
    _extract_spine_texts,
    _merge_into,
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


def test_chunk_spine_truncates_oversized_item():
    items = [{"href": "a.html", "text": "X" * 2000}]
    chunks = _chunk_spine(items, max_chars=500)
    assert len(chunks) == 1
    assert len(chunks[0]["text"]) <= 500


# ---------------------------------------------------------------------------
# _merge_into
# ---------------------------------------------------------------------------

def test_merge_sums_occurrences():
    graph = empty_graph("abc", "test/model")
    partials = [
        {"characters": [{"canonical": "Kirk", "variants": [], "occurrences": 5}],
         "places": [], "organizations": [], "invented_terms": [], "chapters": []},
        {"characters": [{"canonical": "Kirk", "variants": ["James Kirk"], "occurrences": 3}],
         "places": [], "organizations": [], "invented_terms": [], "chapters": []},
    ]
    _merge_into(graph, partials, [])
    chars = graph["entities"]["characters"]
    assert len(chars) == 1
    assert chars[0]["canonical"] == "Kirk"
    assert chars[0]["occurrences"] == 8
    assert "James Kirk" in chars[0]["variants"]


def test_merge_deduplicates_chapters():
    graph = empty_graph("abc", "test/model")
    partials = [
        {"characters": [], "places": [], "organizations": [], "invented_terms": [],
         "chapters": [{"index": 0, "title": "Chapter 1", "spine_item": "a.html", "first_line": "It was"}]},
        {"characters": [], "places": [], "organizations": [], "invented_terms": [],
         "chapters": [{"index": 0, "title": "Chapter 1", "spine_item": "a.html", "first_line": "It was"}]},
    ]
    _merge_into(graph, partials, [])
    assert len(graph["chapters"]) == 1


def test_merge_sorts_by_occurrence():
    graph = empty_graph("abc", "test/model")
    partials = [
        {"characters": [
            {"canonical": "Spock", "variants": [], "occurrences": 2},
            {"canonical": "Kirk", "variants": [], "occurrences": 10},
        ], "places": [], "organizations": [], "invented_terms": [], "chapters": []},
    ]
    _merge_into(graph, partials, [])
    assert graph["entities"]["characters"][0]["canonical"] == "Kirk"


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

    sha = _sha256(epub)
    cached = empty_graph(sha, "cached/model")
    cached["entities"]["characters"] = [{"canonical": "CachedKirk", "variants": [], "occurrences": 1}]
    graph_path = epub.with_suffix(".colophon.json")
    graph_path.write_text(json.dumps(cached), encoding="utf-8")

    cfg = PipelineConfig()

    with patch("colophon.stages.analysis.LLMAdapter") as MockAdapter:
        stage = AnalysisStage()
        ctx: dict = {"epub_path": epub, "config": cfg, "work_dir": work_dir}
        stage.run(ctx)
        MockAdapter.return_value.complete_json.assert_not_called()

    assert ctx["book_graph"]["entities"]["characters"][0]["canonical"] == "CachedKirk"


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
