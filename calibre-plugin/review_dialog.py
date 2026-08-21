"""Calibre dialog for reviewing and applying/reverting/rejecting repair changes."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from calibre.gui2 import error_dialog, info_dialog
from qt.core import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    Qt,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

COL_HEADERS = [
    "#",
    "Status",
    "Stage",
    "Description",
    "Location",
    "Original",
    "Replacement",
]


class ReviewDialog(QDialog):
    """Review changes produced by Colophon for a specific Calibre book."""

    def __init__(self, gui, db, book_id: int, parent=None):
        QDialog.__init__(self, parent or gui)
        self.gui = gui
        self.db = db
        self.book_id = book_id

        title = ""
        try:
            title = self.db.new_api.field_for("title", self.book_id)
        except Exception:
            pass
        if title:
            self.setWindowTitle(f"Colophon — Review changes: {title}")
        else:
            self.setWindowTitle("Colophon — Review changes")

        self.resize(950, 550)

        self.report = self._load_report()

        layout = QVBoxLayout()
        self.setLayout(layout)

        # Top bar: summary counts and status filter
        top_bar = QHBoxLayout()
        self.stats_label = QLabel(self)
        top_bar.addWidget(self.stats_label)
        top_bar.addStretch()

        filter_label = QLabel("Filter:", self)
        top_bar.addWidget(filter_label)

        self.filter_combo = QComboBox(self)
        self.filter_combo.addItems(["All", "Applied", "Flagged", "Skipped"])
        self.filter_combo.currentTextChanged.connect(self._apply_filter)
        top_bar.addWidget(self.filter_combo)

        layout.addLayout(top_bar)

        # Table widget
        self.table = QTableWidget(self)
        self.table.setColumnCount(len(COL_HEADERS))
        self.table.setHorizontalHeaderLabels(COL_HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self.table)

        # Bottom bar: action buttons
        bottom_bar = QHBoxLayout()

        self.btn_apply = QPushButton("Apply selected", self)
        self.btn_apply.setToolTip("Apply selected flagged changes to the EPUB")
        self.btn_apply.clicked.connect(self._on_apply_selected)
        bottom_bar.addWidget(self.btn_apply)

        self.btn_revert = QPushButton("Revert selected", self)
        self.btn_revert.setToolTip("Revert selected applied changes in the EPUB")
        self.btn_revert.clicked.connect(self._on_revert_selected)
        bottom_bar.addWidget(self.btn_revert)

        self.btn_reject = QPushButton("Reject selected", self)
        self.btn_reject.setToolTip("Mark selected changes as skipped (does not edit EPUB)")
        self.btn_reject.clicked.connect(self._on_reject_selected)
        bottom_bar.addWidget(self.btn_reject)

        bottom_bar.addStretch()

        self.btn_close = QPushButton("Close", self)
        self.btn_close.clicked.connect(self.accept)
        bottom_bar.addWidget(self.btn_close)

        layout.addLayout(bottom_bar)

        self._populate_table()

    def _load_report(self) -> dict:
        from calibre_plugins.colophon.book_data import (
            REPORT_RELPATH,
            copy_extra_to_path,
            has_extra_file,
        )

        api = self.db.new_api
        if not has_extra_file(api, self.book_id, REPORT_RELPATH):
            raise ValueError(f"No repair report found for book id {self.book_id}")

        with tempfile.TemporaryDirectory(prefix="colophon_report_") as tmp:
            dest = Path(tmp) / "repair-report.json"
            copy_extra_to_path(api, self.book_id, REPORT_RELPATH, dest)
            with open(dest, encoding="utf-8") as f:
                return json.load(f)

    @staticmethod
    def _format_cell(text: str | None, max_len: int = 80) -> tuple[str, str]:
        """Return (display_text, tooltip_text)."""
        if text is None:
            return "", ""
        raw = str(text)
        clean = " ".join(raw.split())
        if len(clean) > max_len:
            display = clean[: max_len - 3] + "..."
        else:
            display = clean
        return display, raw

    def _populate_table(self):
        changes = self.report.get("changes", []) if self.report else []

        applied = sum(1 for c in changes if c.get("status") == "applied")
        flagged = sum(1 for c in changes if c.get("status") == "flagged")
        skipped = sum(1 for c in changes if c.get("status") == "skipped")
        self.stats_label.setText(
            f"Total: {len(changes)} | Applied: {applied} | Flagged: {flagged} | Skipped: {skipped}"
        )

        self.table.setRowCount(len(changes))
        item_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

        for i, change in enumerate(changes):
            # Col 0: # (1-indexed display, real index stored in UserRole)
            item_num = QTableWidgetItem(str(i + 1))
            item_num.setData(Qt.ItemDataRole.UserRole, i)
            item_num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_num.setFlags(item_flags)
            self.table.setItem(i, 0, item_num)

            # Col 1: Status
            status = str(change.get("status") or "")
            item_status = QTableWidgetItem(status)
            item_status.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_status.setFlags(item_flags)
            self.table.setItem(i, 1, item_status)

            # Col 2: Stage
            stage = str(change.get("stage") or "")
            item_stage = QTableWidgetItem(stage)
            item_stage.setFlags(item_flags)
            self.table.setItem(i, 2, item_stage)

            # Col 3: Description
            desc = str(change.get("description") or "")
            item_desc = QTableWidgetItem(desc)
            item_desc.setToolTip(desc)
            item_desc.setFlags(item_flags)
            self.table.setItem(i, 3, item_desc)

            # Col 4: Location
            loc = str(change.get("location") or "")
            item_loc = QTableWidgetItem(loc)
            item_loc.setToolTip(loc)
            item_loc.setFlags(item_flags)
            self.table.setItem(i, 4, item_loc)

            # Col 5: Original
            orig_disp, orig_raw = self._format_cell(change.get("original"))
            item_orig = QTableWidgetItem(orig_disp)
            if orig_raw:
                item_orig.setToolTip(orig_raw)
            item_orig.setFlags(item_flags)
            self.table.setItem(i, 5, item_orig)

            # Col 6: Replacement
            rep_disp, rep_raw = self._format_cell(change.get("replacement"))
            item_rep = QTableWidgetItem(rep_disp)
            if rep_raw:
                item_rep.setToolTip(rep_raw)
            item_rep.setFlags(item_flags)
            self.table.setItem(i, 6, item_rep)

        self._apply_filter()

    def _apply_filter(self):
        selected_filter = self.filter_combo.currentText().strip().lower()
        changes = self.report.get("changes", []) if self.report else []

        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            idx = item.data(Qt.ItemDataRole.UserRole)
            if idx is None or idx >= len(changes):
                continue
            status = str(changes[idx].get("status") or "").lower()
            if selected_filter == "all" or status == selected_filter:
                self.table.setRowHidden(row, False)
            else:
                self.table.setRowHidden(row, True)

    def _get_selected_change_indices(self) -> list[int]:
        selected_rows = sorted({index.row() for index in self.table.selectedIndexes()})
        indices = []
        for row in selected_rows:
            if not self.table.isRowHidden(row):
                item = self.table.item(row, 0)
                if item is not None:
                    change_idx = item.data(Qt.ItemDataRole.UserRole)
                    if change_idx is not None:
                        indices.append(change_idx)
        return indices

    def _on_apply_selected(self):
        self._perform_action("apply")

    def _on_revert_selected(self):
        self._perform_action("revert")

    def _on_reject_selected(self):
        self._perform_action("reject")

    def _perform_action(self, action_name: str):
        selected_indices = self._get_selected_change_indices()
        if not selected_indices:
            info_dialog(self, "Colophon", "Please select one or more changes first.", show=True)
            return

        from calibre_plugins.colophon.worker import apply_review_actions_for_book

        actions = [(idx, action_name) for idx in selected_indices]
        try:
            res = apply_review_actions_for_book(self.db, self.book_id, actions)
        except Exception as exc:
            error_dialog(self, "Colophon — Review Error", str(exc), show=True)
            return

        if res.get("errors"):
            error_dialog(
                self,
                "Colophon — Review",
                f"{len(res['errors'])} change(s) could not be updated:\n\n"
                + "\n".join(res["errors"]),
                show=True,
            )

        if res.get("report"):
            self.report = res["report"]
            self._populate_table()
