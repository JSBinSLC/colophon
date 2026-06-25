"""Tests for Stage 3 coherence extensions."""
from __future__ import annotations

from colophon.stages.coherence import apply_tier_b_fused, detect_header_footer_lines


def test_tier_b_kelterrified():
    vocab = {"terrified", "that", "the", "doctor", "for", "himself", "but", "and", "jim"}
    entities = {"Kel", "Jim"}
    text = "for Jim and Kelterrified that Jim would draw"
    fixed, changes = apply_tier_b_fused(text, vocab, entities, "—")
    assert "Kel—terrified" in fixed
    assert len(changes) == 1


def test_detect_header_footer():
    blobs = ["Chapter One\nbody\n", "Chapter One\nmore\n", "Chapter One\nend\n"]
    artifacts = detect_header_footer_lines(blobs, {"Chapter One"}, min_repeat=3)
    assert "Chapter One" in artifacts