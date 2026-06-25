"""Stage 4 — Chapter detection & splitting.

When a single spine HTML file contains multiple chapter-level headings, split it
into per-chapter documents and update the OPF manifest and spine order.

Heading detection reuses the same heuristics as Stage 5 (h1/h2, ``Chapter N``
patterns, roman/arabic numerals). Stage 1 graph chapter titles are advisory hints
only — splitting is driven by in-document structure.
"""
from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag
from lxml import etree

from colophon.report import ChangeStatus, Confidence, RepairChange
from colophon.stages import Stage
from colophon.stages.opf_utils import OPF_NS, content_spine_items, next_manifest_id, read_opf, write_opf

log = logging.getLogger(__name__)

_CHAPTER_PAT = re.compile(
    r"^(Chapter|Part|Book|Volume)\s+([IVXLCDM]+|\d+|[A-Za-z]+)\b",
    re.I,
)
_ROMAN_ALONE = re.compile(r"^[IVXLCDM]{1,8}\.?\s*$")
_NUMBER_ALONE = re.compile(r"^\d{1,3}\.?\s*$")


@dataclass
class _SplitPoint:
    tag: Tag
    title: str


class ChapterDetectStage(Stage):
    label = "Stage 4 — Chapter detection & splitting"

    def run(self, ctx: dict) -> None:
        work_dir = ctx.get("work_dir")
        if work_dir is None:
            return

        opf = read_opf(work_dir)
        if opf is None:
            log.warning("Stage 4: could not parse OPF — skipping chapter detection")
            return

        report = ctx["report"]
        splits = 0

        for item in list(content_spine_items(opf)):
            raw = item.abs_path.read_bytes()
            soup = BeautifulSoup(raw, "html5lib")
            points = _find_split_points(soup)
            if len(points) < 2:
                continue

            new_files = _split_document(soup, points, item.abs_path, opf)
            if not new_files:
                continue

            _update_opf_for_split(opf, item, new_files)
            item.abs_path.unlink(missing_ok=True)
            splits += len(new_files)

        if splits:
            write_opf(opf)
            report.add(RepairChange(
                stage="Stage 4",
                description=f"Split {splits} chapter section(s) from monolithic spine files",
                confidence=Confidence.MEDIUM,
                status=ChangeStatus.APPLIED,
            ))

    def analyze(self, ctx: dict) -> None:
        work_dir = ctx.get("work_dir")
        if work_dir is None:
            return

        opf = read_opf(work_dir)
        if opf is None:
            return

        report = ctx["report"]
        would_split = 0

        for item in content_spine_items(opf):
            soup = BeautifulSoup(item.abs_path.read_bytes(), "html5lib")
            points = _find_split_points(soup)
            if len(points) >= 2:
                would_split += len(points)

        if would_split:
            report.add(RepairChange(
                stage="Stage 4",
                description=f"Would split {would_split} chapter section(s)",
                confidence=Confidence.MEDIUM,
                status=ChangeStatus.FLAGGED,
            ))


def _heading_text(tag: Tag) -> str:
    return " ".join(tag.get_text(" ", strip=True).split())


def _looks_like_chapter_heading(text: str) -> bool:
    if not text or len(text) > 150:
        return False
    if _CHAPTER_PAT.match(text) or _ROMAN_ALONE.match(text) or _NUMBER_ALONE.match(text):
        return True
    return text.isupper() and len(text.split()) <= 8


def _find_split_points(soup: BeautifulSoup) -> list[_SplitPoint]:
    body = soup.body
    if body is None:
        return []

    points: list[_SplitPoint] = []
    for tag in body.find_all(["h1", "h2", "p"]):
        if tag.find_parent(["h1", "h2", "h3", "h4", "h5", "h6"]):
            continue
        text = _heading_text(tag)
        if tag.name in ("h1", "h2") and text:
            points.append(_SplitPoint(tag=tag, title=text[:120]))
            continue
        if tag.name == "p" and _looks_like_chapter_heading(text):
            points.append(_SplitPoint(tag=tag, title=text[:120]))

    # Deduplicate by tag object identity while preserving order.
    seen: set[int] = set()
    unique: list[_SplitPoint] = []
    for pt in points:
        key = id(pt.tag)
        if key not in seen:
            seen.add(key)
            unique.append(pt)
    return unique


def _split_document(
    soup: BeautifulSoup,
    points: list[_SplitPoint],
    source_path: Path,
    opf: Any,
) -> list[tuple[str, str, Path]]:
    """Return list of (manifest_id, href, abs_path) for each new chapter file."""
    body = soup.body
    if body is None:
        return []

    sections: list[list[Tag | NavigableString]] = []
    current: list[Tag | NavigableString] = []
    split_tags = {id(pt.tag) for pt in points}
    started = False

    for child in list(body.children):
        if isinstance(child, Tag) and id(child) in split_tags:
            if started and current:
                sections.append(current)
            current = [child]
            started = True
            continue
        if started:
            current.append(child)

    if current:
        sections.append(current)

    if len(sections) < 2:
        return []

    stem = source_path.stem
    parent = source_path.parent
    suffix = source_path.suffix or ".xhtml"
    created: list[tuple[str, str, Path]] = []

    for idx, nodes in enumerate(sections, start=1):
        chapter_soup = _clone_shell(soup)
        chapter_body = chapter_soup.body
        if chapter_body is None:
            continue
        for node in list(chapter_body.children):
            node.extract()
        for node in nodes:
            chapter_body.append(copy.copy(node))

        manifest_id = next_manifest_id(opf, prefix=f"{stem[:20]}_{idx:02d}_")
        href = f"{stem}_ch{idx:02d}{suffix}"
        out_path = parent / href
        out_path.write_text(_serialize(chapter_soup), encoding="utf-8")

        opf.manifest[manifest_id] = {
            "href": href,
            "media_type": "application/xhtml+xml",
            "properties": "",
        }
        created.append((manifest_id, href, out_path))

    return created


def _clone_shell(soup: BeautifulSoup) -> BeautifulSoup:
    """Copy document shell (html/head) without body children."""
    shell = BeautifulSoup(str(soup), "html5lib")
    body = shell.body
    if body is not None:
        for child in list(body.children):
            child.extract()
    return shell


def _update_opf_for_split(
    opf: Any,
    original_item: Any,
    new_files: list[tuple[str, str, Path]],
) -> None:
    manifest = opf.root.find(f"{{{OPF_NS}}}manifest")
    spine = opf.root.find(f"{{{OPF_NS}}}spine")
    if manifest is None or spine is None:
        return

    for manifest_id, href, _ in new_files:
        item = etree.SubElement(manifest, f"{{{OPF_NS}}}item")
        item.set("id", manifest_id)
        item.set("href", href)
        item.set("media-type", "application/xhtml+xml")

    itemrefs = spine.findall(f"{{{OPF_NS}}}itemref")
    insert_at = None
    for i, itemref in enumerate(itemrefs):
        if itemref.get("idref") == original_item.item_id:
            insert_at = i
            spine.remove(itemref)
            break

    if insert_at is None:
        insert_at = len(itemrefs)

    for offset, (manifest_id, _, _) in enumerate(new_files):
        itemref = etree.Element(f"{{{OPF_NS}}}itemref")
        itemref.set("idref", manifest_id)
        spine.insert(insert_at + offset, itemref)

    opf.manifest.pop(original_item.item_id, None)
    for item in manifest.findall(f"{{{OPF_NS}}}item"):
        if item.get("id") == original_item.item_id:
            manifest.remove(item)
            break

    new_spine_items = []
    for itemref in spine.findall(f"{{{OPF_NS}}}itemref"):
        idref = itemref.get("idref", "")
        info = opf.manifest.get(idref)
        if info and info["media_type"] in ("application/xhtml+xml", "text/html"):
            abs_path = opf.opf_dir / info["href"]
            if abs_path.exists():
                from colophon.stages.opf_utils import SpineItem
                new_spine_items.append(SpineItem(
                    item_id=idref,
                    href=info["href"],
                    abs_path=abs_path,
                    media_type=info["media_type"],
                ))
    opf.spine_items = new_spine_items


def _serialize(soup: BeautifulSoup) -> str:
    if soup.html:
        return soup.html.decode()
    if soup.body:
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml">\n'
            f"{soup.body.decode()}\n</html>"
        )
    return str(soup)