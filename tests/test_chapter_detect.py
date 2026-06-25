"""Unit tests for Stage 4 (chapter detection & splitting)."""
from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup
from lxml import etree

from colophon.report import ChangeStatus, RepairReport
from colophon.stages.chapter_detect import (
    ChapterDetectStage,
    _find_split_points,
    _split_document,
)
from colophon.stages.opf_utils import OPF_NS, read_opf

_CONTAINER_XML = """\
<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf"
              media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

_OPF_MONOLITH = """\
<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0"
         unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test Book</dc:title>
    <dc:identifier id="uid">urn:uuid:test</dc:identifier>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="book" href="book.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="book"/></spine>
</package>"""

_MONOLITH_HTML = """\
<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Whole Book</title></head>
  <body>
    <h1>Chapter One</h1>
    <p>First chapter content.</p>
    <h1>Chapter Two</h1>
    <p>Second chapter content.</p>
    <h1>Chapter Three</h1>
    <p>Third chapter content.</p>
  </body>
</html>"""

_SINGLE_CHAPTER = """\
<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <body>
    <h1>Only Chapter</h1>
    <p>All content here.</p>
  </body>
</html>"""


def _setup_monolith(tmp_path: Path, html: str = _MONOLITH_HTML) -> Path:
    work = tmp_path / "work"
    (work / "META-INF").mkdir(parents=True)
    (work / "OEBPS").mkdir()
    (work / "mimetype").write_text("application/epub+zip", encoding="utf-8")
    (work / "META-INF" / "container.xml").write_text(_CONTAINER_XML, encoding="utf-8")
    (work / "OEBPS" / "content.opf").write_text(_OPF_MONOLITH, encoding="utf-8")
    (work / "OEBPS" / "book.xhtml").write_text(html, encoding="utf-8")
    return work


def test_find_split_points_multiple_headings():
    soup = BeautifulSoup(_MONOLITH_HTML, "html5lib")
    points = _find_split_points(soup)
    assert len(points) == 3
    assert points[0].title == "Chapter One"
    assert points[2].title == "Chapter Three"


def test_find_split_points_single_chapter():
    soup = BeautifulSoup(_SINGLE_CHAPTER, "html5lib")
    assert len(_find_split_points(soup)) == 1


def test_split_document_creates_files(tmp_path):
    work = _setup_monolith(tmp_path)
    opf = read_opf(work)
    soup = BeautifulSoup(_MONOLITH_HTML, "html5lib")
    points = _find_split_points(soup)
    source = work / "OEBPS" / "book.xhtml"
    created = _split_document(soup, points, source, opf)
    assert len(created) == 3
    for _, href, path in created:
        assert path.exists()
        assert "Chapter" in path.read_text(encoding="utf-8")


def test_stage_run_updates_opf_and_spine(tmp_path):
    work = _setup_monolith(tmp_path)
    ctx = {
        "work_dir": work,
        "report": RepairReport(source_epub="test.epub"),
        "book_graph": {},
    }
    ChapterDetectStage().run(ctx)

    opf_root = etree.parse(str(work / "OEBPS" / "content.opf")).getroot()
    itemrefs = opf_root.findall(f".//{{{OPF_NS}}}itemref")
    assert len(itemrefs) == 3
    assert not (work / "OEBPS" / "book.xhtml").exists()
    assert len(ctx["report"].changes) == 1
    assert ctx["report"].changes[0].status == ChangeStatus.APPLIED


def test_stage_skips_already_split_book(tmp_path):
    work = _setup_monolith(tmp_path, html=_SINGLE_CHAPTER)
    ctx = {
        "work_dir": work,
        "report": RepairReport(source_epub="test.epub"),
        "book_graph": {},
    }
    ChapterDetectStage().run(ctx)
    assert len(ctx["report"].changes) == 0
    assert (work / "OEBPS" / "book.xhtml").exists()


def test_stage_analyze_dry_run(tmp_path):
    work = _setup_monolith(tmp_path)
    ctx = {
        "work_dir": work,
        "report": RepairReport(source_epub="test.epub"),
        "book_graph": {},
    }
    ChapterDetectStage().analyze(ctx)
    assert ctx["report"].changes[0].status == ChangeStatus.FLAGGED
    assert (work / "OEBPS" / "book.xhtml").exists()