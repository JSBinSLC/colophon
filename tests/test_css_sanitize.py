"""Unit tests for Stage 6 (CSS sanitization)."""
from __future__ import annotations

from pathlib import Path

from colophon.report import ChangeStatus, RepairReport
from colophon.stages.css_sanitize import (
    CssSanitizeStage,
    _has_viewport,
    _normalize_font_sizes,
    _sanitize_css,
    _selector_references_used,
    _strip_fixed_colors,
    _strip_unused_rules,
)

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
    <item id="css" href="style.css" media-type="text/css"/>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="ch1"/></spine>
</package>"""

_CH1 = """\
<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><link rel="stylesheet" href="style.css" type="text/css"/></head>
  <body><p class="used">Hello</p></body>
</html>"""

_MESSY_CSS = """\
body { font-size: 16px; color: #000000; background-color: #ffffff; }
.used { font-size: 18px; }
.dead { font-size: 12px; color: #333; }
p { margin: 0; }
"""


def _setup_work(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    (work / "META-INF").mkdir(parents=True)
    (work / "OEBPS").mkdir()
    (work / "mimetype").write_text("application/epub+zip", encoding="utf-8")
    (work / "META-INF" / "container.xml").write_text(_CONTAINER_XML, encoding="utf-8")
    (work / "OEBPS" / "content.opf").write_text(_OPF, encoding="utf-8")
    (work / "OEBPS" / "style.css").write_text(_MESSY_CSS, encoding="utf-8")
    (work / "OEBPS" / "ch1.xhtml").write_text(_CH1, encoding="utf-8")
    return work


def test_selector_references_used():
    used = {"classes": {"used"}, "ids": set()}
    assert _selector_references_used(".used", used)
    assert not _selector_references_used(".dead", used)
    assert _selector_references_used("p", used)


def test_strip_unused_rules():
    used = {"classes": {"used"}, "ids": set()}
    out = _strip_unused_rules(_MESSY_CSS, used)
    assert ".dead" not in out
    assert ".used" in out


def test_normalize_font_sizes():
    assert "1.125em" in _normalize_font_sizes(".x { font-size: 18px; }")


def test_strip_fixed_colors():
    out = _strip_fixed_colors("p { color: #000; background-color: white; }")
    assert "color" not in out
    assert "background-color" not in out


def test_sanitize_css_combined():
    used = {"classes": {"used"}, "ids": set()}
    out = _sanitize_css(_MESSY_CSS, used)
    assert ".dead" not in out
    assert "px" not in out
    assert "color:" not in out


def test_has_viewport_false(tmp_path):
    f = tmp_path / "ch.xhtml"
    f.write_text("<html><head></head><body/></html>", encoding="utf-8")
    assert not _has_viewport(f)


def test_stage_run_sanitizes_and_adds_viewport(tmp_path):
    work = _setup_work(tmp_path)
    ctx = {
        "work_dir": work,
        "report": RepairReport(source_epub="test.epub"),
    }
    CssSanitizeStage().run(ctx)

    css = (work / "OEBPS" / "style.css").read_text(encoding="utf-8")
    html = (work / "OEBPS" / "ch1.xhtml").read_text(encoding="utf-8")
    assert ".dead" not in css
    assert 'name="viewport"' in html
    assert ctx["report"].changes[0].status == ChangeStatus.APPLIED


def test_stage_analyze_dry_run(tmp_path):
    work = _setup_work(tmp_path)
    ctx = {
        "work_dir": work,
        "report": RepairReport(source_epub="test.epub"),
    }
    CssSanitizeStage().analyze(ctx)
    assert ctx["report"].changes[0].status == ChangeStatus.FLAGGED
    assert ".dead" in (work / "OEBPS" / "style.css").read_text(encoding="utf-8")