"""Unit and integration tests for Stage 5 (TOC & spine reconstruction).

Tests cover:
  - _find_heading: heading detection from HTML
  - _detect_chapters: fallback behaviour when no headings present
  - _write_ncx: XML output structure
  - _write_nav: XML output structure
  - TocRebuildStage.run: end-to-end EPUB 2 and EPUB 3 fixtures
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from lxml import etree

from colophon.report import ChangeStatus, RepairReport
from colophon.stages.toc_rebuild import (
    TocRebuildStage,
    _Chapter,
    _find_heading,
    _write_nav,
    _write_ncx,
)

# ---------------------------------------------------------------------------
# Minimal fixture strings
# ---------------------------------------------------------------------------

_CONTAINER_XML = """\
<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf"
              media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

_OPF_EPUB2 = """\
<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0"
         unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test Book</dc:title>
    <dc:identifier id="uid">urn:uuid:test-123</dc:identifier>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
    <itemref idref="ch2"/>
  </spine>
</package>"""

# No toc attribute on <spine> — triggers NCX001
_OPF_EPUB2_NO_TOC_ATTR = _OPF_EPUB2.replace("<spine>", '<spine notoc="missing">')
_OPF_EPUB2_NO_TOC_ATTR = _OPF_EPUB2  # spine just has no toc attr at all

_OPF_EPUB3 = """\
<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0"
         unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test Book 3</dc:title>
    <dc:identifier id="uid">urn:uuid:test-456</dc:identifier>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml"
          properties="nav"/>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
    <itemref idref="ch2"/>
  </spine>
</package>"""

_NCX_EMPTY = """\
<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"
  "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="urn:uuid:test-123"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>Test Book</text></docTitle>
  <navMap/>
</ncx>"""

# NAV without epub:type="toc" (triggers NAV004)
_NAV_BAD = """\
<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops">
  <body><nav epub:type="landmarks"><ol/></nav></body>
</html>"""

_CH1 = """\
<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <body><h1>Chapter One</h1><p>Some text here.</p></body>
</html>"""

_CH2 = """\
<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <body><h1>Chapter Two</h1><p>More text here.</p></body>
</html>"""

_CH_NO_HEADING = """\
<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <body><p>Just some body text with no heading element at all.</p></body>
</html>"""

_CH_CHAPTER_PATTERN = """\
<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <body><p>Chapter 3</p><p>This chapter's content.</p></body>
</html>"""

_CH_H2 = """\
<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <body><h2>Section Alpha</h2><p>Some text.</p></body>
</html>"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_epub2(tmp_path: Path, ch1: str = _CH1, ch2: str = _CH2) -> Path:
    """Write a minimal EPUB 2 directory; return work_dir."""
    work = tmp_path / "work"
    (work / "META-INF").mkdir(parents=True)
    (work / "OEBPS").mkdir()
    (work / "mimetype").write_text("application/epub+zip", encoding="utf-8")
    (work / "META-INF" / "container.xml").write_text(_CONTAINER_XML, encoding="utf-8")
    (work / "OEBPS" / "content.opf").write_text(_OPF_EPUB2, encoding="utf-8")
    (work / "OEBPS" / "toc.ncx").write_text(_NCX_EMPTY, encoding="utf-8")
    (work / "OEBPS" / "ch1.xhtml").write_text(ch1, encoding="utf-8")
    (work / "OEBPS" / "ch2.xhtml").write_text(ch2, encoding="utf-8")
    return work


def _setup_epub3(tmp_path: Path, ch1: str = _CH1, ch2: str = _CH2) -> Path:
    """Write a minimal EPUB 3 directory; return work_dir."""
    work = tmp_path / "work"
    (work / "META-INF").mkdir(parents=True)
    (work / "OEBPS").mkdir()
    (work / "mimetype").write_text("application/epub+zip", encoding="utf-8")
    (work / "META-INF" / "container.xml").write_text(_CONTAINER_XML, encoding="utf-8")
    (work / "OEBPS" / "content.opf").write_text(_OPF_EPUB3, encoding="utf-8")
    (work / "OEBPS" / "nav.xhtml").write_text(_NAV_BAD, encoding="utf-8")
    (work / "OEBPS" / "ch1.xhtml").write_text(ch1, encoding="utf-8")
    (work / "OEBPS" / "ch2.xhtml").write_text(ch2, encoding="utf-8")
    return work


def _ctx(work: Path, version: str = "2") -> dict:
    return {
        "work_dir": work,
        "report": RepairReport(source_epub="test.epub"),
        "book_graph": {},
        "epub_version": version,
    }


# ---------------------------------------------------------------------------
# _find_heading
# ---------------------------------------------------------------------------

def test_find_heading_h1(tmp_path):
    f = tmp_path / "ch.xhtml"
    f.write_text(_CH1, encoding="utf-8")
    assert _find_heading(f) == "Chapter One"


def test_find_heading_h2(tmp_path):
    f = tmp_path / "ch.xhtml"
    f.write_text(_CH_H2, encoding="utf-8")
    assert _find_heading(f) == "Section Alpha"


def test_find_heading_chapter_pattern(tmp_path):
    f = tmp_path / "ch.xhtml"
    f.write_text(_CH_CHAPTER_PATTERN, encoding="utf-8")
    assert _find_heading(f) == "Chapter 3"


def test_find_heading_none(tmp_path):
    f = tmp_path / "ch.xhtml"
    f.write_text(_CH_NO_HEADING, encoding="utf-8")
    assert _find_heading(f) is None


def test_find_heading_missing_file(tmp_path):
    assert _find_heading(tmp_path / "nonexistent.xhtml") is None


# ---------------------------------------------------------------------------
# _write_ncx
# ---------------------------------------------------------------------------

def test_write_ncx_produces_valid_xml(tmp_path):
    chapters = [
        _Chapter(abs_path=tmp_path / "ch1.xhtml", title="Chapter One", play_order=1),
        _Chapter(abs_path=tmp_path / "ch2.xhtml", title="Chapter Two", play_order=2),
    ]
    ncx_path = tmp_path / "toc.ncx"
    _write_ncx(ncx_path, uid="urn:uuid:x", title="My Book", chapters=chapters)

    # Parseable as XML (lxml parses NCX fine, ignoring the DOCTYPE declaration)
    root = etree.fromstring(ncx_path.read_bytes())
    nav_map = root.find(f"{{{NCX_NS}}}navMap")
    assert nav_map is not None
    nav_points = nav_map.findall(f"{{{NCX_NS}}}navPoint")
    assert len(nav_points) == 2


def test_write_ncx_nav_point_content(tmp_path):
    chapters = [
        _Chapter(abs_path=tmp_path / "ch1.xhtml", title="Chapter One", play_order=1),
    ]
    ncx_path = tmp_path / "toc.ncx"
    _write_ncx(ncx_path, uid="uid", title="Book", chapters=chapters)

    root = etree.fromstring(ncx_path.read_bytes())
    np = root.find(f".//{{{NCX_NS}}}navPoint")
    label = np.find(f"{{{NCX_NS}}}navLabel/{{{NCX_NS}}}text").text
    src   = np.find(f"{{{NCX_NS}}}content").get("src")

    assert label == "Chapter One"
    assert src == "ch1.xhtml"


def test_write_ncx_escapes_special_chars(tmp_path):
    chapters = [
        _Chapter(abs_path=tmp_path / "ch.xhtml", title="Chapter & Friends", play_order=1),
    ]
    ncx_path = tmp_path / "toc.ncx"
    _write_ncx(ncx_path, uid="uid", title="Book", chapters=chapters)
    text = ncx_path.read_text(encoding="utf-8")
    assert "&amp;" in text
    assert "Chapter & Friends" not in text   # raw & must not appear unescaped


# ---------------------------------------------------------------------------
# _write_nav
# ---------------------------------------------------------------------------

NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"


def test_write_nav_produces_valid_xml(tmp_path):
    chapters = [
        _Chapter(abs_path=tmp_path / "ch1.xhtml", title="Chapter One", play_order=1),
        _Chapter(abs_path=tmp_path / "ch2.xhtml", title="Chapter Two", play_order=2),
    ]
    nav_path = tmp_path / "nav.xhtml"
    _write_nav(nav_path, title="My Book", chapters=chapters)

    root = etree.fromstring(nav_path.read_bytes())
    XHTML_NS = "http://www.w3.org/1999/xhtml"
    EPUB_NS  = "http://www.idpf.org/2007/ops"
    nav = root.find(f".//{{{XHTML_NS}}}nav[@{{{EPUB_NS}}}type='toc']")
    assert nav is not None, "nav element with epub:type='toc' not found"


def test_write_nav_link_count(tmp_path):
    chapters = [
        _Chapter(abs_path=tmp_path / "ch1.xhtml", title="One", play_order=1),
        _Chapter(abs_path=tmp_path / "ch2.xhtml", title="Two", play_order=2),
    ]
    nav_path = tmp_path / "nav.xhtml"
    _write_nav(nav_path, title="Book", chapters=chapters)

    XHTML_NS = "http://www.w3.org/1999/xhtml"
    root = etree.fromstring(nav_path.read_bytes())
    links = root.findall(f".//{{{XHTML_NS}}}a")
    assert len(links) == 2
    assert links[0].get("href") == "ch1.xhtml"


# ---------------------------------------------------------------------------
# TocRebuildStage.run — EPUB 2
# ---------------------------------------------------------------------------

def test_stage_epub2_writes_ncx_navpoints(tmp_path):
    work = _setup_epub2(tmp_path)
    ctx  = _ctx(work, "2")
    TocRebuildStage().run(ctx)

    ncx_root = etree.fromstring((work / "OEBPS" / "toc.ncx").read_bytes())
    nav_points = ncx_root.findall(f".//{{{NCX_NS}}}navPoint")
    assert len(nav_points) == 2
    labels = [
        np.find(f"{{{NCX_NS}}}navLabel/{{{NCX_NS}}}text").text
        for np in nav_points
    ]
    assert labels == ["Chapter One", "Chapter Two"]


def test_stage_epub2_sets_spine_toc_attr(tmp_path):
    work = _setup_epub2(tmp_path)
    ctx  = _ctx(work, "2")
    TocRebuildStage().run(ctx)

    OPF_NS = "http://www.idpf.org/2007/opf"
    opf_root = etree.fromstring((work / "OEBPS" / "content.opf").read_bytes())
    spine = opf_root.find(f"{{{OPF_NS}}}spine")
    assert spine is not None
    assert spine.get("toc") == "ncx"


def test_stage_epub2_records_applied_change(tmp_path):
    work = _setup_epub2(tmp_path)
    ctx  = _ctx(work, "2")
    TocRebuildStage().run(ctx)

    assert len(ctx["report"].changes) == 1
    assert ctx["report"].changes[0].status == ChangeStatus.APPLIED


def test_stage_epub2_fallback_no_headings(tmp_path):
    """When no headings exist, every spine item gets a generic title."""
    work = _setup_epub2(tmp_path, ch1=_CH_NO_HEADING, ch2=_CH_NO_HEADING)
    ctx  = _ctx(work, "2")
    TocRebuildStage().run(ctx)

    ncx_root = etree.fromstring((work / "OEBPS" / "toc.ncx").read_bytes())
    nav_points = ncx_root.findall(f".//{{{NCX_NS}}}navPoint")
    assert len(nav_points) == 2   # both spine items included


# ---------------------------------------------------------------------------
# TocRebuildStage.run — EPUB 3
# ---------------------------------------------------------------------------

def test_stage_epub3_writes_nav_xhtml(tmp_path):
    work = _setup_epub3(tmp_path)
    ctx  = _ctx(work, "3")
    TocRebuildStage().run(ctx)

    nav_path = work / "OEBPS" / "nav.xhtml"
    assert nav_path.exists()
    XHTML_NS = "http://www.w3.org/1999/xhtml"
    EPUB_NS  = "http://www.idpf.org/2007/ops"
    root = etree.fromstring(nav_path.read_bytes())
    nav_elem = root.find(f".//{{{XHTML_NS}}}nav[@{{{EPUB_NS}}}type='toc']")
    assert nav_elem is not None


def test_stage_epub3_also_writes_ncx(tmp_path):
    """EPUB 3 must still produce a toc.ncx for backward compatibility."""
    work = _setup_epub3(tmp_path)
    ctx  = _ctx(work, "3")
    TocRebuildStage().run(ctx)

    ncx_root = etree.fromstring((work / "OEBPS" / "toc.ncx").read_bytes())
    nav_points = ncx_root.findall(f".//{{{NCX_NS}}}navPoint")
    assert len(nav_points) == 2


# ---------------------------------------------------------------------------
# TocRebuildStage.run — graceful degradation
# ---------------------------------------------------------------------------

def test_stage_no_op_without_work_dir(tmp_path):
    """Stage must not crash when work_dir contains no OPF."""
    ctx = {
        "work_dir": tmp_path,
        "report": RepairReport(source_epub="x.epub"),
        "book_graph": {},
        "epub_version": "2",
    }
    TocRebuildStage().run(ctx)
    assert len(ctx["report"].changes) == 0


# ---------------------------------------------------------------------------
# Full round-trip: unpack → Stage 5 → repack → validate
# ---------------------------------------------------------------------------

def test_roundtrip_fixes_empty_navmap(tmp_path):
    """End-to-end: EPUB 2 with empty navMap → after Stage 5 + repack, NCX005 is gone."""
    from colophon.stages.repack import _pack_epub
    from colophon.validator import validate

    # Build source EPUB
    src = tmp_path / "src.epub"
    work_src = _setup_epub2(tmp_path / "src_work")
    _pack_epub(work_src, src)

    # Validate before: should have at least one NCX defect
    codes_before = {i.code for i in validate(src).issues}
    assert codes_before & {"NCX001", "NCX005", "NCX008"}

    # Unpack → run Stage 5 → repack
    import shutil, zipfile
    work = tmp_path / "work"
    with zipfile.ZipFile(src) as zf:
        zf.extractall(work)

    ctx = {
        "work_dir": work,
        "report": RepairReport(source_epub=str(src)),
        "book_graph": {},
        "epub_version": "2",
    }
    TocRebuildStage().run(ctx)

    repaired = tmp_path / "repaired.epub"
    _pack_epub(work, repaired)

    # Validate after: NCX005/NCX008 must be gone
    codes_after = {i.code for i in validate(repaired).issues}
    assert "NCX005" not in codes_after, f"NCX005 still present after repair: {codes_after}"
    assert "NCX008" not in codes_after, f"NCX008 still present after repair: {codes_after}"
