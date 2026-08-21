"""Unit tests for the Calibre plugin's host_runner module.

Loaded via importlib (not a normal package import) because calibre-plugin/
is not a valid Python package name and host_runner.py must stay importable
without a `calibre` install at unit-test time.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

from colophon.report import ChangeStatus, Confidence

_MODULE_PATH = Path(__file__).parent.parent / "calibre-plugin" / "host_runner.py"


def _load_host_runner():
    spec = importlib.util.spec_from_file_location("host_runner", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


host_runner = _load_host_runner()


def test_load_report_json_hydrates_changes(tmp_path):
    data = {
        "source_epub": "book.epub",
        "skipped_reason": None,
        "validation": {
            "errors_before": 2,
            "errors_after": 0,
            "warnings_before": 5,
            "warnings_after": 1,
        },
        "changes": [
            {
                "stage": "text_cleanup",
                "description": "fixed ocr confusable",
                "confidence": "high",
                "status": "applied",
                "location": "chapter03.xhtml:42",
                "original": "rn",
                "replacement": "m",
            },
            {
                "stage": "html_repair",
                "description": "flagged ambiguous tag",
                "confidence": "low",
                "status": "flagged",
            },
        ],
    }
    report_path = tmp_path / "repair-report.json"
    report_path.write_text(json.dumps(data), encoding="utf-8")

    report = host_runner.load_report_json(report_path, "book.epub")

    assert len(report.changes) == 2
    summary = report.summary()
    assert summary["applied"] == 1
    assert summary["flagged"] == 1
    assert summary["skipped"] == 0

    first = report.changes[0]
    assert first.stage == "text_cleanup"
    assert first.confidence == Confidence.HIGH
    assert first.status == ChangeStatus.APPLIED
    assert first.location == "chapter03.xhtml:42"
    assert first.original == "rn"
    assert first.replacement == "m"

    second = report.changes[1]
    assert second.status == ChangeStatus.FLAGGED
    assert second.location is None
    assert second.original is None
    assert second.replacement is None

    assert report.validation_errors_before == 2
    assert report.validation_warnings_after == 1


def test_load_report_json_skips_incomplete_rows(tmp_path):
    data = {
        "source_epub": "book.epub",
        "changes": [
            {"stage": "text_cleanup"},  # missing required fields
            {
                "stage": "chapter_detect",
                "description": "ok row",
                "confidence": "medium",
                "status": "skipped",
            },
        ],
    }
    report_path = tmp_path / "repair-report.json"
    report_path.write_text(json.dumps(data), encoding="utf-8")

    report = host_runner.load_report_json(report_path, "book.epub")

    assert len(report.changes) == 1
    assert report.changes[0].stage == "chapter_detect"
    assert report.summary()["skipped"] == 1


def test_load_report_json_missing_file_returns_empty_report(tmp_path):
    report = host_runner.load_report_json(tmp_path / "missing.json", "book.epub")
    assert report.changes == []
    assert report.summary() == {"applied": 0, "flagged": 0, "skipped": 0}


def test_subprocess_kwargs_windows_sets_no_window_flag():
    kwargs = host_runner._subprocess_kwargs(is_windows=True)
    assert kwargs.get("creationflags") == 0x08000000


def test_subprocess_kwargs_posix_has_no_creationflags():
    kwargs = host_runner._subprocess_kwargs(is_windows=False)
    assert "creationflags" not in kwargs


def test_subprocess_kwargs_defaults_to_current_os_name():
    kwargs = host_runner._subprocess_kwargs()
    assert ("creationflags" in kwargs) == (os.name == "nt")
