"""Calibre toolbar action — Repair and Proofread with Colophon."""
from __future__ import annotations

from calibre.gui2 import error_dialog, info_dialog
from calibre.gui2.actions import InterfaceAction
from calibre_plugins.colophon.worker import repair_epub_for_book
from qt.core import QMessageBox, QThread, QToolButton, pyqtSignal


class RepairThread(QThread):
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, db, book_ids):
        QThread.__init__(self)
        self.db = db
        self.book_ids = book_ids

    def run(self):
        try:
            results = []
            for book_id in self.book_ids:
                results.append((book_id, repair_epub_for_book(self.db, book_id)))
            self.finished_ok.emit({"results": results})
        except Exception as exc:  # noqa: BLE001 — surface to GUI
            self.failed.emit(str(exc))


class ColophonAction(InterfaceAction):
    name = "Colophon"
    action_add_menu = True
    popup_type = (
        QToolButton.ToolButtonPopupMode.MenuButtonPopup
        if hasattr(QToolButton, "ToolButtonPopupMode")
        else QToolButton.MenuButtonPopup
    )

    action_spec = (
        "Colophon",
        None,
        "Repair and Proofread with Colophon",
        None,
    )

    def genesis(self):
        # get_icons is injected by Calibre into plugin modules.
        icon = get_icons("images/icon.png", "Colophon")  # type: ignore[name-defined] # noqa: F821
        self.qaction.setIcon(icon)
        self.qaction.triggered.connect(self.repair_selected)

        menu = self.qaction.menu()
        if menu is None:
            from qt.core import QMenu

            menu = QMenu(self.gui)
            self.qaction.setMenu(menu)

        self.create_menu_action(
            menu,
            "colophon_review_last_report",
            "Review last report",
            icon=icon,
            triggered=self.review_last_report,
        )

    def apply_settings(self):
        pass

    def repair_selected(self):
        rows = self.gui.library_view.selectionModel().selectedRows()
        if not rows:
            error_dialog(self.gui, "Colophon", "Select one or more books first.", show=True)
            return

        book_ids = [self.gui.library_view.model().id(r) for r in rows]
        db = self.gui.current_db

        def _has_epub(bid: int) -> bool:
            fmts = db.formats(bid, index_is_id=True)
            if isinstance(fmts, str):
                fmts = [fmts]
            elif not fmts:
                fmts = []
            return "EPUB" in {f.upper() for f in fmts}

        non_epub = [bid for bid in book_ids if not _has_epub(bid)]
        if non_epub:
            error_dialog(
                self.gui,
                "Colophon",
                f"{len(non_epub)} selected book(s) have no EPUB format. "
                "Colophon repairs EPUB only.",
                show=True,
            )
            return

        self.thread = RepairThread(db, book_ids)
        self.thread.finished_ok.connect(self._on_done)
        self.thread.failed.connect(lambda msg: error_dialog(self.gui, "Colophon", msg, show=True))
        self.thread.start()
        info_dialog(
            self.gui,
            "Colophon",
            f"Repairing and proofreading {len(book_ids)} book(s)… "
            "This may take a few minutes.",
            show=True,
        )

    def review_last_report(self):
        rows = self.gui.library_view.selectionModel().selectedRows()
        if not rows:
            error_dialog(self.gui, "Colophon", "Select a book first.", show=True)
            return

        book_id = self.gui.library_view.model().id(rows[0])
        db = self.gui.current_db
        api = db.new_api

        fmts = db.formats(book_id, index_is_id=True)
        if isinstance(fmts, str):
            fmts = [fmts]
        elif not fmts:
            fmts = []
        has_epub = "EPUB" in {f.upper() for f in fmts}

        from calibre_plugins.colophon.book_data import REPORT_RELPATH, has_extra_file

        if not has_epub or not has_extra_file(api, book_id, REPORT_RELPATH):
            error_dialog(
                self.gui,
                "Colophon",
                "No repair report for this book. Run Colophon first.",
                show=True,
            )
            return

        from calibre_plugins.colophon.review_dialog import ReviewDialog

        try:
            dialog = ReviewDialog(self.gui, db, book_id, parent=self.gui)
            dialog.exec()
        except Exception as exc:  # noqa: BLE001 — surface to GUI
            error_dialog(self.gui, "Colophon", str(exc), show=True)

    def _on_done(self, payload: dict):
        lines = []
        first_reviewable_book_id = None
        first_reviewable_title = None
        reviewable_count = 0

        from calibre_plugins.colophon.book_data import REPORT_RELPATH, has_extra_file

        db = self.gui.current_db
        api = db.new_api

        for book_id, result in payload["results"]:
            title = api.field_for("title", book_id) or f"id:{book_id}"
            if result.get("skipped"):
                lines.append(f"{title}: skipped — {result['skipped']}")
            elif result.get("ok"):
                s = result["summary"]
                lines.append(
                    f"{title}: {s['applied']} applied, {s['flagged']} flagged"
                )
                if has_extra_file(api, book_id, REPORT_RELPATH):
                    reviewable_count += 1
                    if first_reviewable_book_id is None:
                        first_reviewable_book_id = book_id
                        first_reviewable_title = title
            else:
                lines.append(f"{title}: failed")

        summary_text = "\n".join(lines) or "Complete."

        if first_reviewable_book_id is not None:
            msg_box = QMessageBox(self.gui)
            msg_box.setWindowTitle("Colophon — done")
            icon_info = getattr(
                getattr(QMessageBox, "Icon", QMessageBox),
                "Information",
                QMessageBox.Information,
            )
            msg_box.setIcon(icon_info)

            if reviewable_count > 1:
                msg_text = (
                    f"{summary_text}\n\n"
                    f"Click 'Review changes…' to open the review dialog for "
                    f"'{first_reviewable_title}' (first of {reviewable_count} repaired books)."
                )
            else:
                msg_text = summary_text

            msg_box.setText(msg_text)
            action_role = getattr(
                getattr(QMessageBox, "ButtonRole", QMessageBox),
                "ActionRole",
                QMessageBox.ActionRole,
            )
            close_btn_type = getattr(
                getattr(QMessageBox, "StandardButton", QMessageBox),
                "Close",
                QMessageBox.Close,
            )
            review_btn = msg_box.addButton("Review changes…", action_role)
            msg_box.addButton(close_btn_type)
            msg_box.setDefaultButton(review_btn)

            msg_box.exec()

            if msg_box.clickedButton() == review_btn:
                from calibre_plugins.colophon.review_dialog import ReviewDialog

                dialog = ReviewDialog(self.gui, db, first_reviewable_book_id, parent=self.gui)
                dialog.exec()
        else:
            info_dialog(self.gui, "Colophon — done", summary_text, show=True)