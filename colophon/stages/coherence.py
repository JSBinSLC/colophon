"""Local coherence repair — Tier B/C/D extensions beyond Tier A."""
from __future__ import annotations

import re
from typing import Any

from colophon.report import ChangeStatus, Confidence, RepairChange

_FUSED_TOKEN = re.compile(r"\b[A-Z][a-z]+[a-z]{4,}\b")
_ATTRIBUTION = re.compile(
    r"\b(she|he|they|I)\s+(thought|wondered|realized|remembered|knew|felt)\b",
    re.I,
)


def apply_tier_b_fused(
    text: str,
    vocab: set[str],
    entities: set[str],
    punctuation_bias: str = "—",
) -> tuple[str, list[RepairChange]]:
    """Split fused entity+word tokens like Kelterrified → Kel—terrified."""
    changes: list[RepairChange] = []
    for match in _FUSED_TOKEN.finditer(text):
        token = match.group(0)
        if _is_known_word(token.lower(), vocab) or token in entities:
            continue
        fix = _try_fused_split(token, vocab, entities, punctuation_bias)
        if fix and fix != token:
            text = text.replace(token, fix, 1)
            changes.append(RepairChange(
                stage="Stage 3",
                description="Tier B fused-word repair",
                confidence=Confidence.MEDIUM,
                status=ChangeStatus.FLAGGED,
                original=token,
                replacement=fix,
            ))
    return text, changes


def _try_fused_split(
    token: str,
    vocab: set[str],
    entities: set[str],
    sep: str,
) -> str | None:
    for i in range(2, len(token) - 2):
        left, right = token[:i], token[i:]
        left_ok = left in entities or _is_known_word(left, vocab)
        right_ok = _is_known_word(right.lower(), vocab) or right.lower() in vocab
        if left_ok and right_ok:
            return f"{left}{sep}{right}"
    return None


def flag_italics_candidates(soup: Any, location: str) -> list[RepairChange]:
    """Flag thought-attribution lines missing <em> markup."""
    flags: list[RepairChange] = []
    for para in soup.find_all("p"):
        text = para.get_text(" ", strip=True)
        if not text or para.find("em"):
            continue
        if _ATTRIBUTION.search(text):
            flags.append(RepairChange(
                stage="Stage 3",
                description="Missing italics candidate (thought attribution)",
                confidence=Confidence.LOW,
                status=ChangeStatus.FLAGGED,
                location=location,
                original=text[:120],
            ))
    return flags


def detect_header_footer_lines(
    spine_texts: list[str],
    chapter_titles: set[str],
    *,
    min_repeat: int = 3,
) -> set[str]:
    """Return lines repeated across sections that match chapter-title bleed."""
    from collections import Counter

    counts: Counter[str] = Counter()
    for blob in spine_texts:
        lines = [ln.strip() for ln in blob.splitlines() if ln.strip()]
        for line in lines[:3] + lines[-3:]:
            if len(line) <= 120:
                counts[line] += 1

    artifacts: set[str] = set()
    for line, n in counts.items():
        if n >= min_repeat and (line in chapter_titles or line.isdigit() or len(line) < 40):
            artifacts.add(line)
    return artifacts


def propose_tier_c(
    token: str,
    adapter: Any | None,
    context: str,
) -> str | None:
    """LLM world-knowledge restoration — flagged only, never auto-applied."""
    if adapter is None:
        return None
    prompt = (
        f'Context: "{context}"\n'
        f'Damaged token: "{token}"\n'
        "Return JSON: {\"restored\": \"...\"} with the minimal conservative fix, "
        "or the same token if unsure. Restoration only — never invent."
    )
    try:
        result = adapter.complete_json(
            "You restore damaged OCR text conservatively.",
            prompt,
        )
        restored = (result.get("restored") or "").strip()
        if restored and restored != token and len(restored) <= len(token) + 4:
            return restored
    except Exception:
        return None
    return None


def _is_known_word(word: str, vocab: set[str]) -> bool:
    return word.lower() in vocab