"""Unit tests for Stage 3 (text cleanup)."""
from __future__ import annotations

from pathlib import Path

from colophon.report import ChangeStatus, RepairReport
from colophon.stages.text_cleanup import (
    TextCleanupStage,
    _apply_proper_noun_map,
    _apply_tier_a_coherence,
    _build_ocr_confusable_map,
    _build_replacement_map,
    _build_vocabulary,
    _clean_text,
    _normalize_unicode,
    run_coherence_corpus,
)

_FIXTURES = Path(__file__).parent / "fixtures"
_GRAPH = {
    "entities": {
        "characters": [
            {"canonical": "Kirk", "variants": ["James T. Kirk"], "occurrences": 5},
            {"canonical": "McCoy", "variants": ["Mc-Coy"], "occurrences": 3},
            {"canonical": "Kel", "variants": [], "occurrences": 2},
        ],
        "places": [],
        "organizations": [],
        "invented_terms": [
            {"canonical": "quark", "variants": [], "occurrences": 1},
        ],
    },
    "chapters": [],
}

_CONTAINER_XML = """\
<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf"
              media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

_OPF = """\
<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0"
         unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test Book</dc:title>
    <dc:identifier id="uid">urn:uuid:test</dc:identifier>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="ch1"/></spine>
</package>"""

_OCR_HTML = """\
<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <body>
    <p>Captain K1rk said hello.</p>
    <p>They walked to gether down the corridor.</p>
    <p>Dr. Mc-Coy was there.</p>
    <p>Line one word-
continued here.</p>
    <p>* * *</p>
  </body>
</html>"""


def _setup_work(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    (work / "META-INF").mkdir(parents=True)
    (work / "OEBPS").mkdir()
    (work / "mimetype").write_text("application/epub+zip", encoding="utf-8")
    (work / "META-INF" / "container.xml").write_text(_CONTAINER_XML, encoding="utf-8")
    (work / "OEBPS" / "content.opf").write_text(_OPF, encoding="utf-8")
    (work / "OEBPS" / "ch1.xhtml").write_text(_OCR_HTML, encoding="utf-8")
    return work


def test_normalize_ligatures():
    assert "fi" in _normalize_unicode("ﬁx")


def test_proper_noun_replacement():
    pairs = _build_replacement_map(_GRAPH)
    text = _apply_proper_noun_map("Mc-Coy arrived.", pairs, _build_vocabulary(_GRAPH))
    assert "McCoy" in text
    assert "Mc-Coy" not in text


def test_tier_a_split_word():
    vocab = _build_vocabulary(_GRAPH)
    ocr = _build_ocr_confusable_map(_GRAPH)
    text = _apply_tier_a_coherence("They walked to gether.", vocab, ocr)
    assert "together" in text


def test_tier_a_ocr_confusable():
    vocab = _build_vocabulary(_GRAPH)
    ocr = _build_ocr_confusable_map(_GRAPH)
    text = _apply_tier_a_coherence("Captain K1rk said.", vocab, ocr)
    assert "Kirk" in text


def test_hard_hyphen_line_break():
    vocab = _build_vocabulary(_GRAPH)
    text = _clean_text("word-\ncontinued", vocab, [], {}, "conventional")
    assert "wordcontinued" not in text  # not a known word — left alone


def test_stage_run_cleans_file(tmp_path):
    work = _setup_work(tmp_path)
    ctx = {
        "work_dir": work,
        "report": RepairReport(source_epub="test.epub"),
        "book_graph": _GRAPH,
    }
    TextCleanupStage().run(ctx)

    out = (work / "OEBPS" / "ch1.xhtml").read_text(encoding="utf-8")
    assert "Kirk" in out
    assert "together" in out
    assert "McCoy" in out
    assert 'epub:type="separator"' in out
    assert any(c.stage == "Stage 3" for c in ctx["report"].changes)


def test_coherence_corpus_all_tiers():
    # Entities a real graph for these books would carry (Kel/Jim are characters
    # in The Lost Years) — needed so the entity-prefixed Tier B split can fire.
    graph = {
        "entities": {
            "characters": [
                {"canonical": "Kirk", "variants": [], "occurrences": 1},
                {"canonical": "Kel", "variants": [], "occurrences": 1},
                {"canonical": "Jim", "variants": [], "occurrences": 1},
            ],
            "places": [],
            "organizations": [],
            "invented_terms": [{"canonical": "quark", "variants": [], "occurrences": 1}],
        },
        "chapters": [],
    }
    results = run_coherence_corpus(_FIXTURES / "coherence-cases.jsonl", graph)
    by_id = {r["id"]: r for r in results}

    # Auto-applied tiers transform to the expected text.
    assert by_id["fused-word-tier-a"]["pass"]
    assert by_id["ocr-confusable-tier-a"]["pass"]
    assert by_id["kelterrified"]["pass"], by_id["kelterrified"]["actual"]
    # Already-correct and flag-only tiers must be left untouched.
    assert by_id["killed-not-a-defect"]["pass"]
    assert by_id["world-knowledge-tier-c"]["pass"]      # flag-only, not auto-applied
    assert by_id["unrecoverable-tier-d"]["pass"]
    # Intentional non-sense must pass through unchanged.
    assert by_id["finnegans-wake-quark"]["pass"]
    assert by_id["finnegans-wake-thunderword"]["pass"]


def test_proper_noun_map_preserves_plurals():
    """Plural inflections of an entity name are NOT spelling variants and must
    not be singularized ("a pair of Organisms" must stay plural)."""
    graph = {
        "entities": {
            "characters": [{"canonical": "McCoy", "variants": ["Mccoy"]}],
            "places": [],
            "organizations": [],
            "invented_terms": [
                {"canonical": "Organism", "variants": ["Organisms"]},
                {"canonical": "Relict", "variants": ["Relicts"]},
            ],
        },
        "chapters": [],
    }
    repl = _build_replacement_map(graph)
    assert ("Organisms", "Organism") not in repl   # plural, not a misspelling
    assert ("Relicts", "Relict") not in repl
    assert ("Mccoy", "McCoy") in repl              # genuine spelling variant kept

    out = _apply_proper_noun_map(
        "a pair of Organisms played while the Relicts watched Mccoy.",
        repl, _build_vocabulary(graph),
    )
    assert "a pair of Organisms played" in out     # the bug: must stay plural
    assert "the Relicts watched" in out
    assert "McCoy" in out                          # misspelling still canonicalized


def test_proper_noun_map_respects_word_boundaries():
    """A short variant must not be replaced inside a longer word."""
    graph = {
        "entities": {
            "characters": [{"canonical": "Finn", "variants": ["Fin"]}],
            "places": [], "organizations": [], "invented_terms": [],
        },
        "chapters": [],
    }
    repl = _build_replacement_map(graph)
    out = _apply_proper_noun_map(
        "Fin dove; the final fin was Finny.", repl, _build_vocabulary(graph),
    )
    assert out.startswith("Finn dove")             # standalone 'Fin' fixed
    assert "the final fin" in out                  # not corrupted inside 'final'/lowercase
    assert "Finny" in out                          # not corrupted inside 'Finny'


def test_stage_analyze_dry_run(tmp_path):
    work = _setup_work(tmp_path)
    ctx = {
        "work_dir": work,
        "report": RepairReport(source_epub="test.epub"),
        "book_graph": _GRAPH,
    }
    TextCleanupStage().analyze(ctx)
    assert ctx["report"].changes[0].status == ChangeStatus.FLAGGED
    assert "K1rk" in (work / "OEBPS" / "ch1.xhtml").read_text(encoding="utf-8")