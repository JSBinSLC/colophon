"""Tests for --interactive review."""
from __future__ import annotations

from unittest.mock import patch

from colophon.config import PipelineConfig
from colophon.interactive import review_flagged_changes
from colophon.report import ChangeStatus, Confidence, RepairChange, RepairReport


def test_interactive_applies_on_yes():
    report = RepairReport(source_epub="x.epub")
    report.add(RepairChange(
        stage="Stage 3",
        description="test change",
        confidence=Confidence.LOW,
        status=ChangeStatus.FLAGGED,
    ))
    ctx = {
        "config": PipelineConfig(interactive=True),
        "report": report,
    }
    with patch("builtins.input", return_value="y"):
        review_flagged_changes(ctx)
    assert report.changes[0].status == ChangeStatus.APPLIED


def test_interactive_skips_on_no():
    report = RepairReport(source_epub="x.epub")
    report.add(RepairChange(
        stage="Stage 3",
        description="test change",
        confidence=Confidence.MEDIUM,
        status=ChangeStatus.FLAGGED,
    ))
    ctx = {
        "config": PipelineConfig(interactive=True),
        "report": report,
    }
    with patch("builtins.input", return_value="n"):
        review_flagged_changes(ctx)
    assert report.changes[0].status == ChangeStatus.FLAGGED