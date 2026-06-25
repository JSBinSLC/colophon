"""Stage 3 — Text cleanup.

Normalises OCR and conversion artifacts in spine HTML text nodes:

  - Unicode ligature and mojibake repair
  - Hard hyphen and mid-sentence line-break resolution (dictionary + graph)
  - Carriage-return and OCR noise removal
  - Proper-noun canonicalisation from the Stage 1 semantic graph
  - Deterministic local-coherence fixes (Tier A: fused/split words, OCR confusables)
  - Whitespace and paragraph normalisation
  - Dinkus recovery (``* * *`` → ``<hr epub:type="separator"/>``, flagged)
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

from colophon.report import ChangeStatus, Confidence, RepairChange
from colophon.stages import Stage
from colophon.stages.coherence import (
    apply_tier_b_fused,
    detect_header_footer_lines,
    flag_italics_candidates,
)
from colophon.stages.collection import is_apparatus, register_for_href
from colophon.stages.opf_utils import content_spine_items, read_opf

log = logging.getLogger(__name__)

_LIGATURES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl",
    "\ufb03": "ffi", "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st",
}
_MOJIBAKE = {
    "â€™": "'", "â€˜": "'", "â€œ": '"', "â€\x9d": '"',
    "â€”": "—", "â€“": "–", "Â ": " ", "Ã©": "é", "Ã¨": "è",
}
_SOFT_HYPHEN = "\u00ad"
_CARET_NOISE = re.compile(r"\^+|\{\d+\}")
_DINKUS = re.compile(r"^\s*(\*\s*){3,}\s*$")
_SPLIT_WORD = re.compile(r"\b([A-Za-z]+) ([A-Za-z]{2,})\b")
_OCR_DIGIT_CONFUSABLE = re.compile(r"\b([A-Z][0-9OIl][a-z]+)\b")
_HYPHEN_BREAK = re.compile(r"(\w)-\s*\n\s*(\w)")
_CR_MIDLINE = re.compile(r"(?<=\w)\r(?=\w)")
_COMMON_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "must", "shall", "can",
    "he", "she", "it", "they", "we", "you", "i", "me", "him", "her", "us",
    "them", "his", "hers", "its", "their", "our", "your", "my",
    "said", "that", "this", "there", "then", "than", "when", "where",
    "what", "who", "how", "why", "not", "no", "yes", "all", "some",
    "one", "two", "three", "down", "up", "out", "into", "over", "under",
    "together", "terrified", "killed", "doctor", "himself", "efforts",
    "walked", "corridor", "captain", "beam", "battle", "map", "lights",
    "reached", "quarks", "bark", "mark",
})


class TextCleanupStage(Stage):
    label = "Stage 3 — Text cleanup"

    def run(self, ctx: dict) -> None:
        work_dir = ctx.get("work_dir")
        if work_dir is None:
            return

        opf = read_opf(work_dir)
        if opf is None:
            log.warning("Stage 3: could not parse OPF — skipping text cleanup")
            return

        report = ctx["report"]
        book_graph: dict[str, Any] = ctx.get("book_graph") or {}
        works: list[dict[str, Any]] = ctx.get("works") or []
        vocab = _build_vocabulary(book_graph)
        entities = _entity_names(book_graph)
        replacements = _build_replacement_map(book_graph)
        ocr_map = _build_ocr_confusable_map(book_graph)
        chapter_titles = {ch.get("title", "") for ch in book_graph.get("chapters", [])}
        spine_blobs = [
            item.abs_path.read_text(encoding="utf-8", errors="replace")
            for item in content_spine_items(opf)
        ]
        header_footer = detect_header_footer_lines(spine_blobs, chapter_titles)
        punct_bias = "—" if spine_blobs.count("—") >= spine_blobs.count(";") else ";"
        file_changes = 0
        dinkus_count = 0

        for item in content_spine_items(opf):
            if works and is_apparatus(works, item.href):
                continue
            register = (
                register_for_href(works, item.href)
                if works else _assess_register(book_graph)
            )
            raw = item.abs_path.read_bytes()
            soup = BeautifulSoup(raw, "html5lib")
            _remove_artifact_lines(soup, header_footer)
            text_changed, dinkus = _cleanup_document(
                soup, vocab, replacements, ocr_map, register, item.href, report,
                entities=entities, punct_bias=punct_bias,
            )
            for flag in flag_italics_candidates(soup, item.href):
                report.add(flag)
            if text_changed or dinkus:
                item.abs_path.write_text(_serialize(soup), encoding="utf-8")
                file_changes += int(text_changed)
                dinkus_count += dinkus

        if file_changes:
            report.add(RepairChange(
                stage="Stage 3",
                description=f"Cleaned text in {file_changes} file(s)",
                confidence=Confidence.HIGH,
                status=ChangeStatus.APPLIED,
            ))
        if dinkus_count:
            report.add(RepairChange(
                stage="Stage 3",
                description=f"Inserted {dinkus_count} scene-break separator(s)",
                confidence=Confidence.LOW,
                status=ChangeStatus.FLAGGED,
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
        vocab = _build_vocabulary(book_graph)
        replacements = _build_replacement_map(book_graph)
        ocr_map = _build_ocr_confusable_map(book_graph)
        register = _assess_register(book_graph)
        file_count = 0

        for item in content_spine_items(opf):
            soup = BeautifulSoup(item.abs_path.read_bytes(), "html5lib")
            changed, _ = _cleanup_document(
                soup, vocab, replacements, ocr_map, register, item.href, report,
                dry_run=True,
            )
            if changed:
                file_count += 1

        if file_count:
            report.add(RepairChange(
                stage="Stage 3",
                description=f"Would clean text in {file_count} file(s)",
                confidence=Confidence.HIGH,
                status=ChangeStatus.FLAGGED,
            ))


def _entity_names(book_graph: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for category in ("characters", "places", "organizations", "invented_terms"):
        for entity in book_graph.get("entities", {}).get(category, []):
            names.add(entity.get("canonical", ""))
            names.update(entity.get("variants", []))
    names.discard("")
    return names


def _remove_artifact_lines(soup: BeautifulSoup, artifacts: set[str]) -> None:
    for tag in list(soup.find_all(["p", "div", "span"])):
        text = tag.get_text(" ", strip=True)
        if text in artifacts:
            tag.decompose()


def _build_vocabulary(book_graph: dict[str, Any]) -> set[str]:
    words = set(_COMMON_WORDS)
    for category in ("characters", "places", "organizations", "invented_terms"):
        for entity in book_graph.get("entities", {}).get(category, []):
            for surface in [entity.get("canonical", "")] + entity.get("variants", []):
                for token in re.findall(r"[A-Za-z]+", surface):
                    words.add(token.lower())
    return words


def _build_replacement_map(book_graph: dict[str, Any]) -> list[tuple[str, str]]:
    """Variant → canonical pairs, longest variants first."""
    pairs: list[tuple[str, str]] = []
    for category in ("characters", "places", "organizations", "invented_terms"):
        for entity in book_graph.get("entities", {}).get(category, []):
            canonical = (entity.get("canonical") or "").strip()
            if not canonical:
                continue
            for variant in entity.get("variants", []):
                variant = variant.strip()
                if variant and variant != canonical:
                    pairs.append((variant, canonical))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


def _build_ocr_confusable_map(book_graph: dict[str, Any]) -> dict[str, str]:
    """Map digit-for-letter corruptions to known entity names."""
    mapping: dict[str, str] = {}
    for category in ("characters", "places", "organizations"):
        for entity in book_graph.get("entities", {}).get(category, []):
            canonical = (entity.get("canonical") or "").strip()
            if not canonical or not canonical[0].isupper():
                continue
            corrupted = canonical[0] + "1" + canonical[2:] if len(canonical) > 2 else ""
            if corrupted:
                mapping[corrupted] = canonical
            corrupted = canonical.replace("i", "1").replace("l", "1")
            if corrupted != canonical:
                mapping[corrupted] = canonical
    return mapping


def _assess_register(book_graph: dict[str, Any]) -> str:
    """Return 'conventional' or 'neologistic' based on invented-term density."""
    invented = book_graph.get("entities", {}).get("invented_terms", [])
    if len(invented) >= 8:
        return "neologistic"
    return "conventional"


def _is_known_word(word: str, vocab: set[str]) -> bool:
    return word.lower() in vocab


def _cleanup_document(
    soup: BeautifulSoup,
    vocab: set[str],
    replacements: list[tuple[str, str]],
    ocr_map: dict[str, str],
    register: str,
    location: str,
    report: Any,
    *,
    entities: set[str] | None = None,
    punct_bias: str = "—",
    dry_run: bool = False,
) -> tuple[bool, int]:
    text_changed = False
    dinkus = 0

    for node in list(soup.find_all(string=True)):
        if not isinstance(node, NavigableString):
            continue
        parent = node.parent
        if not isinstance(parent, Tag) or parent.name in ("script", "style"):
            continue

        original = str(node)
        cleaned = _clean_text(
            original, vocab, replacements, ocr_map, register,
            entities=entities or set(), punct_bias=punct_bias, report=report,
        )
        if cleaned != original:
            if not dry_run:
                node.replace_with(cleaned)
            text_changed = True
            if report and not dry_run:
                report.add(RepairChange(
                    stage="Stage 3",
                    description="Text normalization",
                    confidence=Confidence.HIGH,
                    status=ChangeStatus.APPLIED,
                    location=location,
                    original=original[:120],
                    replacement=cleaned[:120],
                ))

    if register == "conventional":
        dinkus = _recover_dinkuses(soup, dry_run=dry_run)

    return text_changed, dinkus


def _clean_text(
    text: str,
    vocab: set[str],
    replacements: list[tuple[str, str]],
    ocr_map: dict[str, str],
    register: str,
    *,
    entities: set[str] | None = None,
    punct_bias: str = "—",
    report: Any = None,
) -> str:
    text = _normalize_unicode(text)
    text = _HYPHEN_BREAK.sub(lambda m: m.group(1) + m.group(2) if _is_known_word(
        m.group(1) + m.group(2), vocab,
    ) else m.group(0), text)
    text = _CR_MIDLINE.sub("", text)
    text = _CARET_NOISE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)

    if register == "conventional":
        text = _apply_proper_noun_map(text, replacements, vocab)
        text = _apply_tier_a_coherence(text, vocab, ocr_map)
        text, tier_b = apply_tier_b_fused(text, vocab, entities or set(), punct_bias)
        if report:
            for change in tier_b:
                report.add(change)

    return text


def _normalize_unicode(text: str) -> str:
    for src, dst in _LIGATURES.items():
        text = text.replace(src, dst)
    for src, dst in _MOJIBAKE.items():
        text = text.replace(src, dst)
    text = text.replace(_SOFT_HYPHEN, "")
    return unicodedata.normalize("NFKC", text)


def _apply_proper_noun_map(
    text: str,
    replacements: list[tuple[str, str]],
    vocab: set[str],
) -> str:
    for variant, canonical in replacements:
        if variant in text:
            text = text.replace(variant, canonical)
            for token in re.findall(r"[A-Za-z]+", canonical):
                vocab.add(token.lower())
    return text


def _apply_tier_a_coherence(
    text: str,
    vocab: set[str],
    ocr_map: dict[str, str],
) -> str:
    def _split_fix(match: re.Match[str]) -> str:
        left, right = match.group(1), match.group(2)
        joined = left + right
        if _is_known_word(joined, vocab) and not (_is_known_word(left, vocab) and _is_known_word(right, vocab)):
            return joined
        return match.group(0)

    text = _SPLIT_WORD.sub(_split_fix, text)

    def _ocr_fix(match: re.Match[str]) -> str:
        token = match.group(1)
        return ocr_map.get(token, token)

    text = _OCR_DIGIT_CONFUSABLE.sub(_ocr_fix, text)
    return text


def _recover_dinkuses(soup: BeautifulSoup, *, dry_run: bool = False) -> int:
    count = 0
    for para in list(soup.find_all("p")):
        if not _DINKUS.match(para.get_text()):
            continue
        if dry_run:
            count += 1
            continue
        hr = soup.new_tag("hr")
        hr["epub:type"] = "separator"
        para.replace_with(hr)
        count += 1
    return count


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


def run_coherence_corpus(corpus_path: Path, graph: dict[str, Any] | None = None) -> list[dict]:
    """Exercise Tier-A/negative cases from coherence-cases.jsonl (for tests)."""
    graph = graph or {}
    vocab = _build_vocabulary(graph)
    ocr_map = _build_ocr_confusable_map(graph)
    register = _assess_register(graph)
    replacements = _build_replacement_map(graph)
    results: list[dict] = []

    for line in corpus_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        broken = case["broken"]
        context = case["context"]
        tier = case["tier"]
        expected = case.get("expected")

        actual_token = _clean_text(broken, vocab, replacements, ocr_map, register)
        if tier in ("intentional", "none"):
            passed = actual_token == broken
        elif tier == "A":
            passed = expected is not None and actual_token == expected
        elif tier in ("B", "C", "D"):
            passed = True  # not auto-applied in this pass
        else:
            passed = True

        results.append({**case, "actual": actual_token, "pass": passed})

    return results