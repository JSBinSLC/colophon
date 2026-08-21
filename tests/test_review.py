"""Tests for colophon.review apply/revert/reject."""
from __future__ import annotations

from pathlib import Path

import pytest

from colophon.review import ReviewAction, apply_actions


def _work(tmp_path: Path, html: str, name: str = "ch1.xhtml") -> Path:
    work = tmp_path / "work"
    (work / "OEBPS").mkdir(parents=True)
    (work / "OEBPS" / name).write_text(html, encoding="utf-8")
    return work


def _report(*changes: dict) -> dict:
    return {"changes": list(changes)}


def test_apply_replacement(tmp_path: Path):
    html = "<html><body><p>Test text here.</p></body></html>"
    work = _work(tmp_path, html)
    report = _report({
        "status": "flagged",
        "location": "ch1.xhtml",
        "original": "Test",
        "replacement": "Best",
        "description": "fix",
    })
    out = apply_actions(work, report, [ReviewAction(0, "apply")])
    text = (work / "OEBPS" / "ch1.xhtml").read_text(encoding="utf-8")
    assert "Best text here." in text
    assert out["changes"][0]["status"] == "applied"


def test_revert_replacement(tmp_path: Path):
    html = "<html><body><p>Best text here.</p></body></html>"
    work = _work(tmp_path, html)
    report = _report({
        "status": "applied",
        "location": "ch1.xhtml",
        "original": "Test",
        "replacement": "Best",
        "description": "fix",
    })
    out = apply_actions(work, report, [ReviewAction(0, "revert")])
    text = (work / "OEBPS" / "ch1.xhtml").read_text(encoding="utf-8")
    assert "Test text here." in text
    assert out["changes"][0]["status"] == "flagged"


def test_reject_does_not_edit_html(tmp_path: Path):
    html = "<html><body><p>Test text here.</p></body></html>"
    work = _work(tmp_path, html)
    report = _report({
        "status": "flagged",
        "location": "ch1.xhtml",
        "original": "Test",
        "replacement": "Best",
        "description": "fix",
    })
    out = apply_actions(work, report, [ReviewAction(0, "reject")])
    assert (work / "OEBPS" / "ch1.xhtml").read_text(encoding="utf-8") == html
    assert out["changes"][0]["status"] == "skipped"


def test_apply_italics_wrap(tmp_path: Path):
    html = "<html><body><p>Different as chalk and cheese, she thought.</p></body></html>"
    work = _work(tmp_path, html)
    report = _report({
        "status": "flagged",
        "location": "ch1.xhtml",
        "original": "Different as chalk and cheese, she thought.",
        "replacement": None,
        "description": "Missing italics candidate (thought attribution)",
    })
    apply_actions(work, report, [ReviewAction(0, "apply")])
    text = (work / "OEBPS" / "ch1.xhtml").read_text(encoding="utf-8")
    assert "<em>" in text
    assert "she thought." in text


def test_refuse_non_unique_match(tmp_path: Path):
    html = "<html><body><p>foo foo</p></body></html>"
    work = _work(tmp_path, html)
    report = _report({
        "status": "flagged",
        "location": "ch1.xhtml",
        "original": "foo",
        "replacement": "bar",
        "description": "fix",
    })
    with pytest.raises(ValueError, match="not unique"):
        apply_actions(work, report, [ReviewAction(0, "apply")])
    assert (work / "OEBPS" / "ch1.xhtml").read_text(encoding="utf-8") == html
