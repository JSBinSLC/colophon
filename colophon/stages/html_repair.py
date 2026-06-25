"""Stage 2 — HTML structural repair.

Parses each spine HTML document and:

  - Removes inline ``style`` attributes
  - Normalises presentation tags (``b``/``i`` → ``strong``/``em``)
  - Unwraps empty or redundant ``span`` elements
  - Promotes short bold-only paragraphs to ``h2`` when they look like headings
  - Removes standalone header/footer artifact lines that match known chapter
    titles from the Stage 1 semantic graph
"""
from __future__ import annotations

import logging
import re
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

from colophon.report import ChangeStatus, Confidence, RepairChange
from colophon.stages import Stage
from colophon.stages.opf_utils import content_spine_items, read_opf

log = logging.getLogger(__name__)

_CHAPTER_PAT = re.compile(
    r"^(Chapter|Part|Book|Volume)\s+([IVXLCDM]+|\d+|[A-Za-z]+)\b",
    re.I,
)
_ROMAN_ALONE = re.compile(r"^[IVXLCDM]{1,8}\.?\s*$")
_NUMBER_ALONE = re.compile(r"^\d{1,3}\.?\s*$")
_PRESENTATION_TAGS = {"b": "strong", "i": "em"}


class HtmlRepairStage(Stage):
    label = "Stage 2 — HTML structural repair"

    def run(self, ctx: dict) -> None:
        work_dir = ctx.get("work_dir")
        if work_dir is None:
            return

        opf = read_opf(work_dir)
        if opf is None:
            log.warning("Stage 2: could not parse OPF — skipping HTML repair")
            return

        report = ctx["report"]
        book_graph: dict[str, Any] = ctx.get("book_graph") or {}
        artifact_titles = _chapter_titles_from_graph(book_graph)
        total_changes = 0

        for item in content_spine_items(opf):
            raw = item.abs_path.read_bytes()
            soup = BeautifulSoup(raw, "html5lib")
            changes = _repair_document(soup, artifact_titles, item.href)
            if changes:
                item.abs_path.write_text(_serialize(soup), encoding="utf-8")
                total_changes += changes

        if total_changes:
            report.add(RepairChange(
                stage="Stage 2",
                description=f"Repaired HTML structure in {total_changes} file(s)",
                confidence=Confidence.HIGH,
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
        book_graph: dict[str, Any] = ctx.get("book_graph") or {}
        artifact_titles = _chapter_titles_from_graph(book_graph)
        file_count = 0

        for item in content_spine_items(opf):
            soup = BeautifulSoup(item.abs_path.read_bytes(), "html5lib")
            if _repair_document(soup, artifact_titles, item.href, dry_run=True):
                file_count += 1

        if file_count:
            report.add(RepairChange(
                stage="Stage 2",
                description=f"Would repair HTML structure in {file_count} file(s)",
                confidence=Confidence.HIGH,
                status=ChangeStatus.FLAGGED,
            ))


def _chapter_titles_from_graph(book_graph: dict[str, Any]) -> set[str]:
    titles: set[str] = set()
    for ch in book_graph.get("chapters", []):
        title = (ch.get("title") or "").strip()
        if title:
            titles.add(title)
            titles.add(_normalise_title(title))
    return titles


def _normalise_title(title: str) -> str:
    return " ".join(title.split())


def _looks_like_heading(text: str) -> bool:
    text = text.strip()
    if not text or len(text) > 150:
        return False
    if _CHAPTER_PAT.match(text) or _ROMAN_ALONE.match(text) or _NUMBER_ALONE.match(text):
        return True
    return text.isupper() and len(text.split()) <= 8


def _repair_document(
    soup: BeautifulSoup,
    artifact_titles: set[str],
    location: str,
    *,
    dry_run: bool = False,
) -> int:
    """Apply structural repairs. Returns 1 if anything changed, else 0."""
    changed = False
    changed |= _strip_inline_styles(soup)
    changed |= _normalize_presentation_tags(soup)
    changed |= _unwrap_redundant_spans(soup)
    changed |= _promote_heading_paragraphs(soup)
    changed |= _remove_header_footer_artifacts(soup, artifact_titles)
    return int(changed)


def _strip_inline_styles(soup: BeautifulSoup) -> bool:
    changed = False
    for tag in soup.find_all(True):
        if tag.has_attr("style"):
            del tag["style"]
            changed = True
    return changed


def _normalize_presentation_tags(soup: BeautifulSoup) -> bool:
    changed = False
    for old, new in _PRESENTATION_TAGS.items():
        for tag in soup.find_all(old):
            tag.name = new
            changed = True
    return changed


def _unwrap_redundant_spans(soup: BeautifulSoup) -> bool:
    """Unwrap spans that carry no semantic information."""
    changed = False
    for span in list(soup.find_all("span")):
        if not isinstance(span, Tag):
            continue
        keep_attrs = {
            k: v for k, v in span.attrs.items()
            if k not in ("class", "id", "style")
        }
        if keep_attrs:
            continue
        classes = span.get("class") or []
        if any(c and not c.lower().startswith("calibre") for c in classes):
            continue
        span.unwrap()
        changed = True
    return changed


def _promote_heading_paragraphs(soup: BeautifulSoup) -> bool:
    """Turn bold-only short paragraphs into h2 when they look like headings."""
    changed = False
    for para in list(soup.find_all("p")):
        text = para.get_text(" ", strip=True)
        if not _looks_like_heading(text):
            continue
        children = [c for c in para.children if not (isinstance(c, NavigableString) and not c.strip())]
        if len(children) != 1:
            continue
        child = children[0]
        if isinstance(child, NavigableString):
            continue
        if child.name not in ("b", "strong", "span") or child.get_text(strip=True) != text:
            continue
        heading = soup.new_tag("h2")
        heading.string = text
        para.replace_with(heading)
        changed = True
    return changed


def _remove_header_footer_artifacts(soup: BeautifulSoup, artifact_titles: set[str]) -> bool:
    """Drop standalone lines that duplicate a known chapter title mid-document."""
    if not artifact_titles:
        return False

    changed = False
    for tag_name in ("p", "div", "span"):
        for tag in list(soup.find_all(tag_name)):
            text = tag.get_text(" ", strip=True)
            if not text or len(text) > 120:
                continue
            if text not in artifact_titles and _normalise_title(text) not in artifact_titles:
                continue
            if tag.find_parent(["h1", "h2", "h3", "h4", "h5", "h6"]):
                continue
            tag.decompose()
            changed = True
    return changed


def _serialize(soup: BeautifulSoup) -> str:
    """Return XHTML-safe serialized document."""
    if soup.html:
        return soup.html.decode()
    if soup.body:
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml">\n'
            f"{soup.body.decode()}\n</html>"
        )
    return str(soup)