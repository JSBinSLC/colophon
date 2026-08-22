"""Gate proper-noun swaps so already-valid sentences are not rewritten.

SPEC: never touch text that is already valid. The entity graph proposes
aliases; a parse/sense check must reject swaps that turn good prose into
nonsense (Greek food → Greece food).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

log = logging.getLogger(__name__)

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def enclosing_sentence(text: str, start: int, end: int) -> str:
    left = max(text.rfind(".", 0, start), text.rfind("!", 0, start), text.rfind("?", 0, start))
    if left == -1:
        sent_start = 0
    else:
        sent_start = left + 1
    tail = text[end:]
    m = re.search(r"[.!?]", tail)
    sent_end = end + (m.end() if m else len(tail))
    return text[sent_start:sent_end].strip()


def original_already_valid(sentence: str, variant: str, canonical: str) -> bool | None:
    """True if the original sentence is already fine (do not swap).

    Cheap attributive check first (Greek food). spaCy when available.
    Returns None only when no signal is available.
    """
    if re.search(rf"\b{re.escape(variant)}\s+[a-z]", sentence):
        return True
    nlp = _load_spacy()
    if nlp is None:
        return None
    doc = nlp(sentence)
    for token in doc:
        if token.text != variant:
            continue
        if token.pos_ == "ADJ" or token.dep_ == "amod":
            return True
        if token.ent_type_ in {"NORP", "LANGUAGE"}:
            return True
    return False


def llm_should_apply(
    complete_json: Callable[[str, str], Any],
    items: list[dict[str, str]],
) -> list[bool]:
    """Ask the model whether each proposed sentence is a real fix.

    Apply only when the original is ungrammatical or does not make sense
    and the proposal is grammatical and meaning-preserving.
    """
    if not items:
        return []
    numbered = []
    for i, item in enumerate(items):
        numbered.append(
            f"{i}. ORIGINAL: {item['original']}\n   PROPOSED: {item['proposed']}\n"
            f"   SWAP: {item['variant']} → {item['canonical']}"
        )
    system = (
        "You adjudicate ebook proofreading swaps. "
        "Apply a swap ONLY if the ORIGINAL sentence is ungrammatical "
        "or does not make sense, AND the PROPOSED sentence is grammatical "
        "and keeps the same meaning. "
        "If the original already makes sense, reject. "
        "Adjectives must not become country names "
        "(Greek food, French wine, Chinese characters). "
        "Return JSON: {\"decisions\": [{\"id\": 0, \"apply\": false}, ...]} "
        "with one object per item, ids in order."
    )
    user = "Decide apply true/false for each:\n\n" + "\n".join(numbered)
    data = complete_json(system, user)
    decisions = data.get("decisions") if isinstance(data, dict) else data
    by_id: dict[int, bool] = {}
    if isinstance(decisions, list):
        for row in decisions:
            if isinstance(row, dict) and "id" in row:
                by_id[int(row["id"])] = bool(row.get("apply"))
    return [by_id.get(i, False) for i in range(len(items))]


def allow_swap(
    sentence: str,
    variant: str,
    canonical: str,
    *,
    complete_json: Callable[[str, str], Any] | None = None,
) -> bool:
    """False = leave the original. True = apply the swap."""
    already = original_already_valid(sentence, variant, canonical)
    if already is True:
        return False
    if complete_json is None:
        return False
    proposed = sentence.replace(variant, canonical, 1)
    return llm_should_apply(
        complete_json,
        [{"original": sentence, "proposed": proposed, "variant": variant, "canonical": canonical}],
    )[0]


_NLP = None
_NLP_TRIED = False


def _load_spacy():
    global _NLP, _NLP_TRIED
    if _NLP_TRIED:
        return _NLP
    _NLP_TRIED = True
    try:
        import spacy
    except ImportError:
        return None
    for name in ("en_core_web_sm", "en_core_web_md", "en_core_web_lg"):
        try:
            _NLP = spacy.load(name)
            return _NLP
        except OSError:
            continue
    return None
