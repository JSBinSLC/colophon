"""Tests for sentence-sense gating of risky proper-noun swaps."""
from __future__ import annotations

from colophon.stages.sense_gate import (
    allow_swap,
    enclosing_sentence,
    llm_should_apply,
    original_already_valid,
)
from colophon.stages.text_cleanup import (
    _apply_proper_noun_map,
    _build_risky_replacement_map,
    _build_vocabulary,
)


def test_enclosing_sentence():
    text = "Hello. Some Greek food. Done."
    start = text.index("Greek")
    assert enclosing_sentence(text, start, start + 5) == "Some Greek food."


def test_attributive_greek_is_already_valid():
    assert original_already_valid("Some Greek mythology nonsense.", "Greek", "Greece") is True
    assert original_already_valid("The Greek woman smiled.", "Greek", "Greece") is True


def test_allow_swap_blocks_attributive_even_with_eager_llm():
    def eager(_system: str, _user: str):
        return {"decisions": [{"id": 0, "apply": True}]}

    assert allow_swap(
        "The Greek woman ordered food.",
        "Greek",
        "Greece",
        complete_json=eager,
    ) is False


def test_llm_can_approve_nonsensical_original():
    def judge(_system: str, _user: str):
        return {"decisions": [{"id": 0, "apply": True}]}

    assert allow_swap(
        "They landed in Greek.",
        "Greek",
        "Greece",
        complete_json=judge,
    ) is True


def test_llm_reject_means_no_swap():
    def judge(_system: str, _user: str):
        return {"decisions": [{"id": 0, "apply": False}]}

    assert allow_swap(
        "They landed in Greek.",
        "Greek",
        "Greece",
        complete_json=judge,
    ) is False


def test_llm_should_apply_parses_ids():
    def fake(_s: str, _u: str):
        return {"decisions": [{"id": 1, "apply": True}, {"id": 0, "apply": False}]}

    out = llm_should_apply(
        fake,
        [
            {"original": "a", "proposed": "b", "variant": "a", "canonical": "b"},
            {"original": "c", "proposed": "d", "variant": "c", "canonical": "d"},
        ],
    )
    assert out == [False, True]


def test_risky_map_is_gated_not_blind():
    graph = {
        "entities": {
            "places": [{"canonical": "Greece", "variants": ["Greek"]}],
            "characters": [],
            "organizations": [],
            "invented_terms": [],
        }
    }
    risky = _build_risky_replacement_map(graph)
    assert ("Greek", "Greece") in risky

    def gate(variant: str, canonical: str, text: str, start: int, end: int) -> bool:
        return text[start:end] == "Greek" and text[start - 3 : start] == "in "

    out = _apply_proper_noun_map(
        "The Greek woman landed in Greek.",
        risky,
        _build_vocabulary(graph),
        gate=gate,
    )
    assert "Greek woman" in out
    assert "in Greece" in out
