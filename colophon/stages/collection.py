"""Collection / omnibus detection — Collection → Work → Chapter hierarchy.

Detects 'complete works' style EPUBs from navigation structure and partitions
spine items into works so downstream stages can scope register assessment and
entity extraction per work rather than per file.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from lxml import etree

from colophon.stages import Stage
from colophon.stages.opf_utils import read_opf

log = logging.getLogger(__name__)

_NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
_GROUPING_PAT = re.compile(
    r"^(The|A)\s+(Novels|Short Stories|Poetry|Plays|Works|Collections)\b",
    re.I,
)
_APPARATUS_PAT = re.compile(
    r"^(Title\s+Page|Copyright|Contents|List\s+of|Catalogue|Introduction|Index)\b",
    re.I,
)
_NEOLOGISTIC_WORKS = frozenset({
    "finnegans wake", "ulysses", "a portrait of the artist as a young man",
})


@dataclass
class WorkSpan:
    title: str
    hrefs: list[str] = field(default_factory=list)
    kind: str = "work"  # work | grouping | apparatus
    register: str = "conventional"  # conventional | neologistic


class CollectionDetectStage(Stage):
    label = "Stage 1b — Collection / omnibus detection"

    def run(self, ctx: dict) -> None:
        work_dir = ctx.get("work_dir")
        if work_dir is None:
            return
        works = detect_works(work_dir)
        if works:
            ctx["works"] = [w.__dict__ for w in works]
            ctx["is_omnibus"] = len([w for w in works if w.kind == "work"]) > 1
            log.info("Collection: detected %d work(s) in omnibus", len(works))

    def analyze(self, ctx: dict) -> None:
        self.run(ctx)


def detect_works(work_dir: Path) -> list[WorkSpan]:
    """Infer work boundaries from NCX/nav TOC structure."""
    opf = read_opf(work_dir)
    if opf is None:
        return []

    entries = _read_nav_entries(work_dir, opf)
    if not entries:
        return _fallback_single_work(opf)

    works: list[WorkSpan] = []
    for title, href in entries:
        kind = _classify_entry(title)
        register = "neologistic" if title.lower() in _NEOLOGISTIC_WORKS else "conventional"
        if kind == "grouping":
            works.append(WorkSpan(title=title, kind="grouping", register=register))
            continue
        if kind == "apparatus":
            works.append(WorkSpan(title=title, hrefs=[href] if href else [], kind="apparatus", register="conventional"))
            continue
        works.append(WorkSpan(title=title, hrefs=[href] if href else [], kind="work", register=register))

    if len([w for w in works if w.kind == "work"]) <= 1:
        return _fallback_single_work(opf)
    return works


def _classify_entry(title: str) -> str:
    if _GROUPING_PAT.match(title):
        return "grouping"
    if _APPARATUS_PAT.match(title):
        return "apparatus"
    return "work"


def _fallback_single_work(opf: Any) -> list[WorkSpan]:
    hrefs = [item.href for item in opf.spine_items]
    return [WorkSpan(title=opf.title, hrefs=hrefs, kind="work")]


def _read_nav_entries(work_dir: Path, opf: Any) -> list[tuple[str, str]]:
    """Return top-level (title, href) pairs from NCX or nav.xhtml."""
    if opf.ncx_href:
        ncx_path = opf.opf_dir / opf.ncx_href
        if ncx_path.exists():
            return _parse_ncx(ncx_path)
    if opf.nav_href:
        nav_path = opf.opf_dir / opf.nav_href
        if nav_path.exists():
            return _parse_nav(nav_path)
    return []


def _parse_ncx(ncx_path: Path) -> list[tuple[str, str]]:
    try:
        root = etree.parse(str(ncx_path)).getroot()
    except etree.XMLSyntaxError:
        return []
    nav_map = root.find(f".//{{{_NCX_NS}}}navMap")
    if nav_map is None:
        return []
    entries: list[tuple[str, str]] = []
    for np in nav_map.findall(f"{{{_NCX_NS}}}navPoint"):
        label = np.find(f"{{{_NCX_NS}}}navLabel/{{{_NCX_NS}}}text")
        content = np.find(f"{{{_NCX_NS}}}content")
        title = (label.text or "").strip() if label is not None else ""
        href = content.get("src", "") if content is not None else ""
        if title:
            entries.append((title, href))
    return entries


def _parse_nav(nav_path: Path) -> list[tuple[str, str]]:
    soup = BeautifulSoup(nav_path.read_bytes(), "html5lib")
    toc = soup.find("nav", attrs={"epub:type": "toc"}) or soup.find("nav")
    if toc is None:
        return []
    entries: list[tuple[str, str]] = []
    for li in toc.find_all("li", recursive=False):
        link = li.find("a")
        if link:
            entries.append((link.get_text(strip=True), link.get("href", "")))
    return entries


def register_for_href(works: list[dict[str, Any]], href: str) -> str:
    """Return per-work register for a spine href (conventional/neologistic)."""
    name = Path(href).name
    for work in works:
        if work.get("kind") != "work":
            continue
        for whref in work.get("hrefs", []):
            if name == Path(whref).name or href.endswith(Path(whref).name):
                return work.get("register", "conventional")
    return "conventional"


def is_apparatus(works: list[dict[str, Any]], href: str) -> bool:
    name = Path(href).name
    for work in works:
        if work.get("kind") != "apparatus":
            continue
        for whref in work.get("hrefs", []):
            if name == Path(whref).name:
                return True
    return False