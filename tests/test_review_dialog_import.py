"""Unit tests for the Calibre plugin's review dialog module and worker review helper."""
from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

_PLUGIN_DIR = Path(__file__).parent.parent / "calibre-plugin"
_REVIEW_DIALOG_PATH = _PLUGIN_DIR / "review_dialog.py"
_WORKER_PATH = _PLUGIN_DIR / "worker.py"
_BOOK_DATA_PATH = _PLUGIN_DIR / "book_data.py"
_EMBED_PATH = _PLUGIN_DIR / "embed.py"


def _load_review_dialog_with_mocks():
    """Load review_dialog.py, mocking qt.core and calibre.gui2 if not present."""
    mock_qt_created = False
    mock_calibre_created = False

    if "qt.core" not in sys.modules:
        qt_mod = ModuleType("qt")
        qt_core_mod = ModuleType("qt.core")

        # Provide dummy base classes so ReviewDialog can inherit normally
        class DummyQDialog:
            def __init__(self, *args, **kwargs):
                pass

        qt_core_mod.QDialog = DummyQDialog
        qt_core_mod.QTableWidget = MagicMock()
        qt_core_mod.QTableWidgetItem = MagicMock()
        qt_core_mod.QPushButton = MagicMock()
        qt_core_mod.QComboBox = MagicMock()
        qt_core_mod.QVBoxLayout = MagicMock()
        qt_core_mod.QHBoxLayout = MagicMock()
        qt_core_mod.QHeaderView = MagicMock()
        qt_core_mod.QAbstractItemView = MagicMock()
        qt_core_mod.QLabel = MagicMock()
        qt_core_mod.Qt = MagicMock()

        sys.modules["qt"] = qt_mod
        sys.modules["qt.core"] = qt_core_mod
        mock_qt_created = True

    if "calibre.gui2" not in sys.modules:
        gui2_mock = MagicMock()
        sys.modules["calibre"] = sys.modules.get("calibre", MagicMock())
        sys.modules["calibre.gui2"] = gui2_mock
        mock_calibre_created = True

    try:
        spec = importlib.util.spec_from_file_location("review_dialog", _REVIEW_DIALOG_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if mock_qt_created:
            sys.modules.pop("qt.core", None)
            sys.modules.pop("qt", None)
        if mock_calibre_created:
            sys.modules.pop("calibre.gui2", None)


def _load_worker_with_plugin_env():
    """Load worker.py with calibre_plugins.colophon package set up in sys.modules."""
    root_pkg = ModuleType("calibre_plugins")
    colophon_pkg = ModuleType("calibre_plugins.colophon")
    sys.modules["calibre_plugins"] = root_pkg
    sys.modules["calibre_plugins.colophon"] = colophon_pkg

    spec_embed = importlib.util.spec_from_file_location(
        "calibre_plugins.colophon.embed", _EMBED_PATH
    )
    embed_mod = importlib.util.module_from_spec(spec_embed)
    sys.modules["calibre_plugins.colophon.embed"] = embed_mod
    spec_embed.loader.exec_module(embed_mod)

    spec_bd = importlib.util.spec_from_file_location(
        "calibre_plugins.colophon.book_data", _BOOK_DATA_PATH
    )
    bd_mod = importlib.util.module_from_spec(spec_bd)
    sys.modules["calibre_plugins.colophon.book_data"] = bd_mod
    spec_bd.loader.exec_module(bd_mod)

    spec_worker = importlib.util.spec_from_file_location(
        "calibre_plugins.colophon.worker", _WORKER_PATH
    )
    worker_mod = importlib.util.module_from_spec(spec_worker)
    sys.modules["calibre_plugins.colophon.worker"] = worker_mod
    spec_worker.loader.exec_module(worker_mod)

    return worker_mod


def test_review_dialog_module_can_be_imported():
    mod = _load_review_dialog_with_mocks()
    assert hasattr(mod, "ReviewDialog")
    assert hasattr(mod, "COL_HEADERS")
    assert mod.COL_HEADERS == [
        "#",
        "Status",
        "Stage",
        "Description",
        "Location",
        "Original",
        "Replacement",
    ]


def test_review_dialog_format_cell():
    mod = _load_review_dialog_with_mocks()
    cls = mod.ReviewDialog

    assert cls._format_cell(None) == ("", "")
    assert cls._format_cell("") == ("", "")
    assert cls._format_cell("short text") == ("short text", "short text")

    long_text = "word " * 30
    disp, raw = cls._format_cell(long_text, max_len=40)
    assert len(disp) <= 40
    assert disp.endswith("...")
    assert raw == long_text

    multiline = "line1\nline2\tline3"
    disp, raw = cls._format_cell(multiline)
    assert disp == "line1 line2 line3"
    assert raw == multiline


def test_apply_review_actions_for_book(tmp_path):
    # Create a mock EPUB
    epub_file = tmp_path / "sample.epub"
    with zipfile.ZipFile(epub_file, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("OEBPS/chapter1.xhtml", "<html><body><p>Test text</p></body></html>")

    report_data = {
        "source_epub": str(epub_file),
        "changes": [
            {
                "stage": "text_cleanup",
                "description": "change 1",
                "confidence": "high",
                "status": "flagged",
                "location": "chapter1.xhtml",
                "original": "Test",
                "replacement": "Best",
            },
            {
                "stage": "text_cleanup",
                "description": "change 2",
                "confidence": "high",
                "status": "flagged",
                "location": "chapter1.xhtml",
                "original": "invalid",
                "replacement": "fail",
            },
        ],
    }

    # Mock DB and API
    db = MagicMock()
    api = MagicMock()
    db.new_api = api
    db.formats.return_value = ["EPUB"]

    @dataclass
    class ExtraEntry:
        relpath: str

    api.list_extra_files.return_value = [ExtraEntry("data/repair-report.json")]

    def fake_copy_format_to(book_id, fmt, dest_path):
        import shutil

        shutil.copy(epub_file, dest_path)

    api.copy_format_to.side_effect = fake_copy_format_to

    def fake_copy_extra(book_id, relpath, out_stream):
        out_stream.write(json.dumps(report_data).encode("utf-8"))

    api.copy_extra_file_to.side_effect = fake_copy_extra

    # Mock colophon.review
    review_mock = ModuleType("colophon.review")

    @dataclass
    class FakeReviewAction:
        index: int
        action: str

    def fake_apply_actions(work_dir, report, actions):
        res_report = dict(report)
        for act in actions:
            if act.index == 1:
                raise ValueError("cannot apply non-unique change")
            res_report["changes"][act.index]["status"] = "applied"
        return res_report

    review_mock.ReviewAction = FakeReviewAction
    review_mock.apply_actions = fake_apply_actions
    sys.modules["colophon.review"] = review_mock

    try:
        worker = _load_worker_with_plugin_env()
        actions = [(0, "apply"), (1, "apply")]
        res = worker.apply_review_actions_for_book(db, 1, actions)

        assert res["ok"] is True
        assert res["succeeded"] == 1
        assert res["failed"] == 1
        assert len(res["errors"]) == 1
        assert "Change #2: cannot apply non-unique change" in res["errors"][0]
        assert res["report"]["changes"][0]["status"] == "applied"

        # Verify db.add_format was called because HTML was mutated
        assert db.add_format.called
        # Verify extra file was published
        assert api.add_extra_files.called
    finally:
        sys.modules.pop("colophon.review", None)
