"""Stage 5 — TOC & Spine Reconstruction.

Scans each spine HTML document for chapter-level headings (h1/h2), maps them
to their source file, then writes:

  - toc.ncx       EPUB 2 navigation; always written for backward compatibility
  - nav.xhtml     EPUB 3 navigation; written/replaced for EPUB 3 books
  - content.opf   updated spine toc attribute and manifest entries

Defect codes fixed: NCX001, NCX005, NCX008, NAV003 (by replacement), NAV004.
"""
from __future__ import annotations

import html as _html
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from lxml import etree

from colophon.report import ChangeStatus, Confidence, RepairChange
from colophon.stages import Stage

log = logging.getLogger(__name__)

OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS  = "http://purl.org/dc/elements/1.1/"
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"

_CHAPTER_PAT = re.compile(
    r"^(Chapter|Part|Book|Volume)\s+([IVXLCDM]+|\d+|[A-Za-z]+)\b",
    re.I,
)
_ROMAN_ALONE  = re.compile(r"^[IVXLCDM]{1,8}\.?\s*$")
_NUMBER_ALONE = re.compile(r"^\d{1,3}\.?\s*$")


# ---------------------------------------------------------------------------
# Internal data classes
# ---------------------------------------------------------------------------

@dataclass
class _SpineItem:
    item_id: str
    href: str       # OPF-relative
    abs_path: Path


@dataclass
class _OPFInfo:
    path: Path
    opf_dir: Path
    root: Any           # lxml Element (the parsed OPF)
    uid: str
    title: str
    version: str        # "2" or "3"
    spine_items: list[_SpineItem] = field(default_factory=list)
    ncx_id: str | None = None
    ncx_href: str | None = None   # OPF-relative path to existing NCX
    nav_id: str | None = None
    nav_href: str | None = None   # OPF-relative path to existing nav.xhtml


@dataclass
class _Chapter:
    abs_path: Path
    title: str
    play_order: int


# ---------------------------------------------------------------------------
# Stage
# ---------------------------------------------------------------------------

class TocRebuildStage(Stage):
    label = "Stage 5 — TOC & spine reconstruction"

    def run(self, ctx: dict) -> None:
        work_dir: Path = ctx["work_dir"]
        report = ctx["report"]
        book_graph: dict = ctx.get("book_graph") or {}

        opf = _read_opf(work_dir)
        if opf is None:
            log.warning("Stage 5: could not parse OPF — skipping TOC rebuild")
            return
        if not opf.spine_items:
            log.warning("Stage 5: no spine items found — skipping TOC rebuild")
            return

        chapters = _detect_chapters(opf, book_graph)
        if not chapters:
            log.warning("Stage 5: no chapters detected — skipping TOC rebuild")
            return

        messages: list[str] = []

        # Always write toc.ncx for EPUB 2 backward compatibility.
        ncx_href = opf.ncx_href or "toc.ncx"
        ncx_path = opf.opf_dir / ncx_href
        _write_ncx(ncx_path, opf.uid, opf.title, chapters)
        messages.append(f"toc.ncx: {len(chapters)} navPoints")

        ncx_id = opf.ncx_id or "ncx"
        actual_ncx_id = _ensure_manifest_item(
            opf.root, ncx_id, ncx_href, "application/x-dtbncx+xml",
        )
        _set_spine_toc(opf.root, actual_ncx_id)

        # EPUB 3: also write nav.xhtml.
        if opf.version == "3":
            nav_href = opf.nav_href or "nav.xhtml"
            nav_path = opf.opf_dir / nav_href
            _write_nav(nav_path, opf.title, chapters)
            messages.append(f"nav.xhtml: {len(chapters)} entries")
            nav_id = opf.nav_id or "nav"
            _ensure_manifest_item(
                opf.root, nav_id, nav_href,
                "application/xhtml+xml", properties="nav",
            )

        _write_xml(opf.root, opf.path)

        report.add(RepairChange(
            stage="Stage 5",
            description="; ".join(messages),
            confidence=Confidence.HIGH,
            status=ChangeStatus.APPLIED,
        ))

    def analyze(self, ctx: dict) -> None:
        pass


# ---------------------------------------------------------------------------
# OPF parsing
# ---------------------------------------------------------------------------

def _read_opf(work_dir: Path) -> _OPFInfo | None:
    """Parse the OPF and return a structured summary, or None on failure."""
    container = work_dir / "META-INF" / "container.xml"
    if not container.exists():
        return None
    try:
        c_root = etree.parse(str(container)).getroot()
    except etree.XMLSyntaxError:
        return None

    cnt_ns = {"cnt": "urn:oasis:names:tc:opendocument:xmlns:container"}
    rootfiles = c_root.findall(".//cnt:rootfile", cnt_ns)
    if not rootfiles:
        return None

    opf_path = work_dir / rootfiles[0].get("full-path", "")
    if not opf_path.exists():
        return None

    try:
        opf_root = etree.parse(str(opf_path)).getroot()
    except etree.XMLSyntaxError:
        return None

    opf_dir = opf_path.parent
    version = "3" if opf_root.get("version", "2").startswith("3") else "2"

    # Book UID
    uid_attr = opf_root.get("unique-identifier", "uid")
    uid_elem = opf_root.find(f".//{{{DC_NS}}}identifier[@id='{uid_attr}']")
    if uid_elem is None:
        uid_elem = opf_root.find(f".//{{{DC_NS}}}identifier")
    uid = (uid_elem.text or "").strip() if uid_elem is not None else "unknown"

    # Book title
    title_elem = opf_root.find(f".//{{{DC_NS}}}title")
    title = (title_elem.text or "").strip() if title_elem is not None else "Unknown"

    # Manifest → {id: {href, media_type, properties}}
    manifest: dict[str, dict] = {}
    for item in opf_root.findall(f".//{{{OPF_NS}}}item"):
        iid  = item.get("id", "")
        href = item.get("href", "")
        if iid and href:
            manifest[iid] = {
                "href":       href,
                "media_type": item.get("media-type", ""),
                "properties": item.get("properties", ""),
            }

    # Spine items in document order
    spine_items: list[_SpineItem] = []
    for itemref in opf_root.findall(f".//{{{OPF_NS}}}itemref"):
        idref = itemref.get("idref", "")
        info  = manifest.get(idref)
        if info and info["media_type"] in ("application/xhtml+xml", "text/html"):
            abs_path = opf_dir / info["href"]
            if abs_path.exists():
                spine_items.append(_SpineItem(
                    item_id=idref, href=info["href"], abs_path=abs_path,
                ))

    # Locate existing NCX and nav entries
    ncx_id = ncx_href = nav_id = nav_href = None
    for iid, info in manifest.items():
        if info["media_type"] == "application/x-dtbncx+xml" and ncx_id is None:
            ncx_id, ncx_href = iid, info["href"]
        if "nav" in info.get("properties", "") and nav_id is None:
            nav_id, nav_href = iid, info["href"]

    return _OPFInfo(
        path=opf_path, opf_dir=opf_dir, root=opf_root,
        uid=uid, title=title, version=version,
        spine_items=spine_items,
        ncx_id=ncx_id, ncx_href=ncx_href,
        nav_id=nav_id, nav_href=nav_href,
    )


# ---------------------------------------------------------------------------
# Chapter detection
# ---------------------------------------------------------------------------

def _find_heading(html_path: Path) -> str | None:
    """Return the first chapter-level heading text from a spine HTML file."""
    try:
        raw = html_path.read_bytes()
    except OSError:
        return None

    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "nav", "aside"]):
        tag.decompose()

    # h1/h2 are definitive chapter headings.
    for tag_name in ("h1", "h2"):
        for h in soup.find_all(tag_name):
            text = h.get_text(" ", strip=True)
            if text and len(text) <= 200:
                return text

    # Paragraph-level patterns: "Chapter 3", "PART TWO", roman/arabic numerals alone.
    for line in soup.get_text("\n", strip=True).splitlines():
        line = line.strip()
        if not line or len(line) > 150:
            continue
        if (_CHAPTER_PAT.match(line)
                or _ROMAN_ALONE.match(line)
                or _NUMBER_ALONE.match(line)):
            return line

    return None


def _clean_title(title: str) -> str:
    title = " ".join(title.split())
    return title[:120]


def _detect_chapters(opf: _OPFInfo, book_graph: dict) -> list[_Chapter]:
    """Build ordered chapter list from spine headings.

    Prefers h1/h2 from each HTML file. When NO headings are found across the
    whole spine (e.g. text-only pages), falls back to one entry per spine item
    with generic names, optionally seeded from Stage 1 graph titles.
    """
    graph_titles = [ch.get("title", "") for ch in book_graph.get("chapters", [])]

    chapters: list[_Chapter] = []
    for item in opf.spine_items:
        if item.item_id == opf.nav_id:
            continue   # never list the nav document itself as a chapter
        title = _find_heading(item.abs_path)
        if title:
            chapters.append(_Chapter(
                abs_path=item.abs_path,
                title=_clean_title(title),
                play_order=len(chapters) + 1,
            ))

    if not chapters:
        log.info("Stage 5: no headings found - using generic chapter titles")
        idx = 0
        for item in opf.spine_items:
            if item.item_id == opf.nav_id:
                continue
            fallback = (graph_titles[idx] if idx < len(graph_titles)
                        else f"Section {idx + 1}")
            chapters.append(_Chapter(
                abs_path=item.abs_path,
                title=_clean_title(fallback) if fallback else f"Section {idx + 1}",
                play_order=idx + 1,
            ))
            idx += 1

    return chapters


# ---------------------------------------------------------------------------
# TOC writers
# ---------------------------------------------------------------------------

def _rel_from(base_dir: Path, target: Path) -> str:
    """Compute a forward-slash relative path from base_dir to target."""
    return Path(os.path.relpath(str(target), str(base_dir))).as_posix()


def _write_ncx(path: Path, uid: str, title: str, chapters: list[_Chapter]) -> None:
    """Write a complete toc.ncx with one navPoint per chapter."""
    ncx_dir = path.parent
    nav_points = "\n".join(
        (
            f'    <navPoint id="navpoint-{ch.play_order}" playOrder="{ch.play_order}">\n'
            f'      <navLabel><text>{_html.escape(ch.title)}</text></navLabel>\n'
            f'      <content src="{_html.escape(_rel_from(ncx_dir, ch.abs_path))}"/>\n'
            f'    </navPoint>'
        )
        for ch in chapters
    )
    content = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"\n'
        '  "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        '  <head>\n'
        f'    <meta name="dtb:uid" content="{_html.escape(uid)}"/>\n'
        '    <meta name="dtb:depth" content="1"/>\n'
        '    <meta name="dtb:totalPageCount" content="0"/>\n'
        '    <meta name="dtb:maxPageNumber" content="0"/>\n'
        '  </head>\n'
        f'  <docTitle><text>{_html.escape(title)}</text></docTitle>\n'
        '  <navMap>\n'
        f'{nav_points}\n'
        '  </navMap>\n'
        '</ncx>\n'
    )
    path.write_text(content, encoding="utf-8")


def _write_nav(path: Path, title: str, chapters: list[_Chapter]) -> None:
    """Write a nav.xhtml with epub:type='toc' nav element."""
    nav_dir = path.parent
    items = "\n".join(
        (
            f'        <li>'
            f'<a href="{_html.escape(_rel_from(nav_dir, ch.abs_path))}">'
            f'{_html.escape(ch.title)}</a></li>'
        )
        for ch in chapters
    )
    content = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"\n'
        '      xmlns:epub="http://www.idpf.org/2007/ops">\n'
        '  <head>\n'
        '    <meta charset="utf-8"/>\n'
        f'    <title>{_html.escape(title)}</title>\n'
        '  </head>\n'
        '  <body>\n'
        '    <nav epub:type="toc" id="toc">\n'
        f'      <h1>{_html.escape(title)}</h1>\n'
        '      <ol>\n'
        f'{items}\n'
        '      </ol>\n'
        '    </nav>\n'
        '  </body>\n'
        '</html>\n'
    )
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# OPF patching
# ---------------------------------------------------------------------------

def _ensure_manifest_item(
    opf_root: Any,
    item_id: str,
    href: str,
    media_type: str,
    properties: str = "",
) -> str:
    """Add or update a manifest <item>. Returns the ID actually used."""
    manifest = opf_root.find(f"{{{OPF_NS}}}manifest")
    if manifest is None:
        return item_id

    # Search: by explicit id, then by media-type (NCX), then by properties (nav).
    existing = manifest.find(f"{{{OPF_NS}}}item[@id='{item_id}']")
    if existing is None and media_type == "application/x-dtbncx+xml":
        existing = manifest.find(
            f"{{{OPF_NS}}}item[@media-type='application/x-dtbncx+xml']"
        )
    if existing is None and properties == "nav":
        existing = manifest.find(f"{{{OPF_NS}}}item[@properties='nav']")

    if existing is not None:
        actual_id = existing.get("id", item_id)
        existing.set("href", href)
        existing.set("media-type", media_type)
        if properties:
            existing.set("properties", properties)
        return actual_id

    item = etree.SubElement(manifest, f"{{{OPF_NS}}}item")
    item.set("id",         item_id)
    item.set("href",       href)
    item.set("media-type", media_type)
    if properties:
        item.set("properties", properties)
    return item_id


def _set_spine_toc(opf_root: Any, ncx_id: str) -> None:
    """Set the spine toc attribute to the NCX manifest ID (fixes NCX001)."""
    spine = opf_root.find(f"{{{OPF_NS}}}spine")
    if spine is not None:
        spine.set("toc", ncx_id)


def _write_xml(root: Any, path: Path) -> None:
    """Serialise an lxml element tree back to disk."""
    content = etree.tostring(
        root, pretty_print=True, xml_declaration=True, encoding="utf-8",
    )
    path.write_bytes(content)
