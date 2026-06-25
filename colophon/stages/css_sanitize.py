"""Stage 6 — CSS sanitization.

Cleans stylesheet files referenced by the EPUB package:

  - Removes rules for class/id selectors not used in any spine HTML
  - Normalises ``font-size`` pixel values to ``em`` (16px base)
  - Strips hardcoded ``color`` and ``background-color`` that break night mode
  - Ensures each spine document has a viewport meta tag for mobile readers
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from colophon.report import ChangeStatus, Confidence, RepairChange
from colophon.stages import Stage
from colophon.stages.opf_utils import content_spine_items, read_opf

log = logging.getLogger(__name__)

_PX_FONT = re.compile(
    r"(font-size\s*:\s*)(\d+(?:\.\d+)?)px",
    re.I,
)
_FIXED_COLOR = re.compile(
    r"(?<![a-z-])(color|background-color)\s*:\s*[^;}\n]+;?",
    re.I,
)
_CLASS_SEL = re.compile(r"\.([a-zA-Z_][\w-]*)")
_ID_SEL = re.compile(r"#([a-zA-Z_][\w-]*)")


class CssSanitizeStage(Stage):
    label = "Stage 6 — CSS sanitization"

    def run(self, ctx: dict) -> None:
        work_dir = ctx.get("work_dir")
        if work_dir is None:
            return

        opf = read_opf(work_dir)
        if opf is None:
            log.warning("Stage 6: could not parse OPF — skipping CSS sanitization")
            return

        report = ctx["report"]
        used = _collect_used_tokens(opf)
        css_files = _find_css_files(opf)
        css_changed = 0
        viewport_changed = 0

        for css_path in css_files:
            original = css_path.read_text(encoding="utf-8", errors="replace")
            cleaned = _sanitize_css(original, used)
            if cleaned != original:
                css_path.write_text(cleaned, encoding="utf-8")
                css_changed += 1

        for item in content_spine_items(opf):
            if _ensure_viewport(item.abs_path):
                viewport_changed += 1

        messages: list[str] = []
        if css_changed:
            messages.append(f"sanitized {css_changed} stylesheet(s)")
        if viewport_changed:
            messages.append(f"added viewport meta to {viewport_changed} file(s)")

        if messages:
            report.add(RepairChange(
                stage="Stage 6",
                description="; ".join(messages),
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
        used = _collect_used_tokens(opf)
        css_would = sum(
            1 for p in _find_css_files(opf)
            if _sanitize_css(p.read_text(encoding="utf-8", errors="replace"), used)
            != p.read_text(encoding="utf-8", errors="replace")
        )
        viewport_would = sum(
            1 for item in content_spine_items(opf)
            if not _has_viewport(item.abs_path)
        )

        if css_would or viewport_would:
            parts = []
            if css_would:
                parts.append(f"would sanitize {css_would} stylesheet(s)")
            if viewport_would:
                parts.append(f"would add viewport meta to {viewport_would} file(s)")
            report.add(RepairChange(
                stage="Stage 6",
                description="; ".join(parts),
                confidence=Confidence.HIGH,
                status=ChangeStatus.FLAGGED,
            ))


def _find_css_files(opf: Any) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for info in opf.manifest.values():
        if info.get("media_type") == "text/css":
            path = (opf.opf_dir / info["href"]).resolve()
            if path.exists() and path not in seen:
                seen.add(path)
                paths.append(path)
    return paths


def _collect_used_tokens(opf: Any) -> dict[str, set[str]]:
    classes: set[str] = set()
    ids: set[str] = set()
    for item in content_spine_items(opf):
        soup = BeautifulSoup(item.abs_path.read_bytes(), "html5lib")
        for tag in soup.find_all(True):
            for cls in tag.get("class") or []:
                classes.add(cls)
            tag_id = tag.get("id")
            if tag_id:
                ids.add(tag_id)
    return {"classes": classes, "ids": ids}


def _selector_references_used(selector: str, used: dict[str, set[str]]) -> bool:
    """True when the selector should be kept (uses a live token or is element-only)."""
    classes = _CLASS_SEL.findall(selector)
    ids = _ID_SEL.findall(selector)
    if not classes and not ids:
        return True
    class_hit = any(c in used["classes"] for c in classes)
    id_hit = any(i in used["ids"] for i in ids)
    return class_hit or id_hit


def _sanitize_css(css: str, used: dict[str, set[str]]) -> str:
    css = _strip_unused_rules(css, used)
    css = _normalize_font_sizes(css)
    css = _strip_fixed_colors(css)
    return css


def _strip_unused_rules(css: str, used: dict[str, set[str]]) -> str:
    """Drop rule blocks whose selectors only reference unused classes/ids."""
    out: list[str] = []
    i = 0
    while i < len(css):
        brace = css.find("{", i)
        if brace == -1:
            out.append(css[i:])
            break
        selector_block = css[i:brace]
        close = css.find("}", brace)
        if close == -1:
            out.append(css[i:])
            break
        body = css[brace:close + 1]
        selectors = [s.strip() for s in selector_block.split(",") if s.strip()]
        if not selectors or any(_selector_references_used(sel, used) for sel in selectors):
            out.append(selector_block + body)
        i = close + 1
    return "".join(out)


def _normalize_font_sizes(css: str) -> str:
    def _repl(match: re.Match[str]) -> str:
        px = float(match.group(2))
        em = round(px / 16.0, 4)
        em_str = f"{em:g}"
        return f"{match.group(1)}{em_str}em"

    return _PX_FONT.sub(_repl, css)


def _strip_fixed_colors(css: str) -> str:
    return _FIXED_COLOR.sub("", css)


def _has_viewport(html_path: Path) -> bool:
    try:
        soup = BeautifulSoup(html_path.read_bytes(), "html5lib")
    except OSError:
        return True
    head = soup.head
    if head is None:
        return False
    for meta in head.find_all("meta"):
        name = (meta.get("name") or "").lower()
        if name == "viewport":
            return True
    return False


def _ensure_viewport(html_path: Path) -> bool:
    if _has_viewport(html_path):
        return False

    soup = BeautifulSoup(html_path.read_bytes(), "html5lib")
    html = soup.html
    if html is None:
        return False

    head = soup.head
    if head is None:
        head = soup.new_tag("head")
        if html.contents:
            html.insert(0, head)
        else:
            html.append(head)

    meta = soup.new_tag("meta")
    meta["name"] = "viewport"
    meta["content"] = "width=device-width, initial-scale=1.0"
    head.insert(0, meta)

    html_path.write_text(_serialize_html(soup), encoding="utf-8")
    return True


def _serialize_html(soup: BeautifulSoup) -> str:
    if soup.html:
        return soup.html.decode()
    return str(soup)