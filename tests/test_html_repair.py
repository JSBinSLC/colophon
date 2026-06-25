"""Unit tests for Stage 2 (HTML structural repair)."""
from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

from colophon.report import ChangeStatus, RepairReport
from colophon.stages.html_repair import (
    HtmlRepairStage,
    _promote_heading_paragraphs,
    _remove_header_footer_artifacts,
    _repair_document,
    _strip_inline_styles,
    _unwrap_redundant_spans,
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
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="ch1"/></spine>
</package>"""

_MESSY_HTML = """\
<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <body>
    <p style="margin:0"><span class="calibre1" style="font-weight:bold">Chapter 3</span></p>
    <p>Chapter One</p>
    <p style="color:red">Some <span class="calibre2"><b>bold</b></span> text.</p>
  </body>
</html>"""


def _setup_work(tmp_path: Path, html: str = _MESSY_HTML) -> Path:
    work = tmp_path / "work"
    (work / "META-INF").mkdir(parents=True)
    (work / "OEBPS").mkdir()
    (work / "mimetype").write_text("application/epub+zip", encoding="utf-8")
    (work / "META-INF" / "container.xml").write_text(_CONTAINER_XML, encoding="utf-8")
    (work / "OEBPS" / "content.opf").write_text(_OPF, encoding="utf-8")
    (work / "OEBPS" / "ch1.xhtml").write_text(html, encoding="utf-8")
    return work


def test_strip_inline_styles():
    soup = BeautifulSoup('<p style="margin:0">x</p>', "html5lib")
    assert _strip_inline_styles(soup)
    assert soup.p.get("style") is None


def test_unwrap_calibre_spans():
    soup = BeautifulSoup('<p><span class="calibre1">text</span></p>', "html5lib")
    assert _unwrap_redundant_spans(soup)
    assert soup.find("span") is None


def test_promote_bold_chapter_paragraph():
    soup = BeautifulSoup('<p><b>Chapter 3</b></p>', "html5lib")
    assert _promote_heading_paragraphs(soup)
    assert soup.find("h2") is not None
    assert soup.find("h2").get_text(strip=True) == "Chapter 3"


def test_remove_header_footer_artifact():
    soup = BeautifulSoup(
        "<body><p>Chapter One</p><p>Real content here.</p></body>",
        "html5lib",
    )
    titles = {"Chapter One"}
    assert _remove_header_footer_artifacts(soup, titles)
    assert "Chapter One" not in soup.get_text()


def test_repair_document_combined():
    soup = BeautifulSoup(_MESSY_HTML, "html5lib")
    graph = {"chapters": [{"title": "Chapter One"}]}
    assert _repair_document(soup, {"Chapter One"}, "ch1.xhtml")
    text = soup.get_text()
    assert "Chapter One" not in text
    assert "Some bold text." in text.replace("\n", " ")


def test_stage_run_writes_repaired_file(tmp_path):
    work = _setup_work(tmp_path)
    ctx = {
        "work_dir": work,
        "report": RepairReport(source_epub="test.epub"),
        "book_graph": {"chapters": [{"title": "Chapter One"}]},
    }
    HtmlRepairStage().run(ctx)

    out = (work / "OEBPS" / "ch1.xhtml").read_text(encoding="utf-8")
    assert "style=" not in out
    assert len(ctx["report"].changes) == 1
    assert ctx["report"].changes[0].status == ChangeStatus.APPLIED


def test_stage_analyze_dry_run(tmp_path):
    work = _setup_work(tmp_path)
    ctx = {
        "work_dir": work,
        "report": RepairReport(source_epub="test.epub"),
        "book_graph": {"chapters": [{"title": "Chapter One"}]},
    }
    HtmlRepairStage().analyze(ctx)
    assert ctx["report"].changes[0].status == ChangeStatus.FLAGGED
    assert "style=" in (work / "OEBPS" / "ch1.xhtml").read_text(encoding="utf-8")