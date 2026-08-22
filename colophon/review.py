"""Apply, revert, or reject individual repair-report changes in an unpacked EPUB."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

_ITALICS_DESC = "Missing italics candidate (thought attribution)"
_JOIN_DESC = "Joined mid-sentence paragraph wrap"


@dataclass
class ReviewAction:
    index: int
    action: str  # apply | revert | reject


def apply_actions(work_dir: Path, report: dict, actions: list[ReviewAction]) -> dict:
    """Mutate spine HTML under work_dir and return an updated report dict.

    Raises ValueError if a change cannot be applied uniquely.
    """
    updated = copy.deepcopy(report)
    changes = updated.setdefault("changes", [])
    for act in actions:
        if act.action not in {"apply", "revert", "reject"}:
            raise ValueError(f"Unknown review action: {act.action}")
        if act.index < 0 or act.index >= len(changes):
            raise ValueError(f"Change index out of range: {act.index}")
        change = changes[act.index]
        status = change.get("status")
        description = change.get("description") or ""

        if act.action == "reject":
            if status == "applied":
                raise ValueError("Reject does not undo applied HTML; revert first")
            change["status"] = "skipped"
            continue
        if act.action == "apply" and status == "applied":
            raise ValueError("Change is already applied")
        if act.action == "revert" and status != "applied":
            raise ValueError("Only applied changes can be reverted")
        if description == _JOIN_DESC:
            raise ValueError(
                "Paragraph-join rows cannot be applied or reverted from the report"
            )

        original = change.get("original")
        replacement = change.get("replacement")
        if not original and not replacement:
            raise ValueError("Summary-only change has no text to apply or revert")
        path = _resolve_location(work_dir, change.get("location"))
        html = path.read_text(encoding="utf-8", errors="replace")
        if act.action == "apply":
            html = _apply_one(html, change, original, replacement)
            change["status"] = "applied"
        else:
            html = _revert_one(html, original, replacement)
            change["status"] = "flagged"
        path.write_text(html, encoding="utf-8")
    return updated


def _resolve_location(work_dir: Path, location: str | None) -> Path:
    if not location:
        raise ValueError("Change has no location")
    name = Path(location.split(":")[0]).name
    matches = [p for p in work_dir.rglob("*") if p.is_file() and p.name == name]
    if not matches:
        matches = [p for p in work_dir.rglob("*") if p.is_file() and p.as_posix().endswith(location)]
    if len(matches) != 1:
        raise ValueError(f"Could not uniquely resolve location {location!r}")
    return matches[0]


def _apply_one(html: str, change: dict, original: str | None, replacement: str | None) -> str:
    if replacement:
        if not original:
            raise ValueError("Replacement present but original text is missing")
        return _swap_unique(html, original, replacement)
    if change.get("description") == _ITALICS_DESC and original:
        return _wrap_italics(html, original)
    raise ValueError("Cannot apply this change: no replacement text")


def _revert_one(html: str, original: str | None, replacement: str | None) -> str:
    if not original or not replacement:
        raise ValueError("Cannot revert: original and replacement are both required")
    return _swap_unique(html, replacement, original)


def _swap_unique(html: str, find: str, repl: str) -> str:
    count = html.count(find)
    if count == 0:
        raise ValueError("Text not found in file")
    if count > 1:
        raise ValueError("Match is not unique")
    return html.replace(find, repl, 1)


def _wrap_italics(html: str, original: str) -> str:
    """Wrap a unique plaintext span in <em> without reserializing the file."""
    needle = original.strip()
    if not needle:
        raise ValueError("Italics candidate is empty")
    if html.count(needle) != 1:
        raise ValueError("Italics candidate is not unique")
    if "<" in needle or ">" in needle:
        raise ValueError("Italics candidate contains markup")
    start = html.find(needle)
    return html[:start] + "<em>" + needle + "</em>" + html[start + len(needle) :]
