"""spaCy-based NER fallback when no LLM API key is configured."""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_MODEL_NAMES = ("en_core_web_sm", "en_core_web_md", "en_core_web_lg")


def extract_entities(text: str) -> dict[str, list[dict[str, Any]]]:
    """Return a partial graph fragment with characters and places from spaCy NER."""
    nlp = _load_model()
    if nlp is None:
        return {"characters": [], "places": [], "organizations": [], "invented_terms": []}

    # Limit input size for local performance.
    sample = text[:200_000]
    doc = nlp(sample)

    characters: dict[str, dict[str, Any]] = {}
    places: dict[str, dict[str, Any]] = {}
    orgs: dict[str, dict[str, Any]] = {}

    for ent in doc.ents:
        name = ent.text.strip()
        if not name or len(name) < 2:
            continue
        bucket: dict[str, dict[str, Any]]
        if ent.label_ == "PERSON":
            bucket = characters
        elif ent.label_ in ("GPE", "LOC", "FAC"):
            bucket = places
        elif ent.label_ == "ORG":
            bucket = orgs
        else:
            continue
        record = bucket.setdefault(name, {"canonical": name, "variants": [], "occurrences": 0})
        record["occurrences"] += 1

    return {
        "characters": list(characters.values()),
        "places": list(places.values()),
        "organizations": list(orgs.values()),
        "invented_terms": [],
    }


def _load_model():
    try:
        import spacy
    except ImportError:
        log.warning("spaCy not installed; NER fallback unavailable")
        return None

    for name in _MODEL_NAMES:
        try:
            return spacy.load(name)
        except OSError:
            continue

    log.warning(
        "No spaCy English model found. Install with: python -m spacy download en_core_web_sm"
    )
    return None