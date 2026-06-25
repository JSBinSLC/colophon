"""Calibre toolbar action — Repair and Proofread with Colophon."""
from __future__ import annotations

from calibre.gui2.actions import InterfaceAction
from calibre.gui2 import error_dialog, info_dialog
from qt.core import QThread, pyqtSignal

from calibre_plugins.colophon.worker import repair_epub_for_book


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

    action_spec = (
        "Repair and Proofread with Colophon",
        None,
        "Repair and proofread EPUB structure, navigation, and OCR artifacts",
        None,
    )

    def genesis(self):
        self.qaction.triggered.connect(self.repair_selected)

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
            return "EPUB" in {f.upper() for f in fmts}

        non_epub = [bid for bid in book_ids if not _has_epub(bid)]
        if non_epub:
            error_dialog(
                self.gui,
                "Colophon",
                f"{len(non_epub)} selected book(s) have no EPUB format. Colophon repairs EPUB only.",
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

    def _on_done(self, payload: dict):
        lines = []
        for book_id, result in payload["results"]:
            title = self.gui.current_db.new_api.field_for("title", book_id) or f"id:{book_id}"
            if result.get("skipped"):
                lines.append(f"{title}: skipped — {result['skipped']}")
            elif result.get("ok"):
                s = result["summary"]
                lines.append(
                    f"{title}: {s['applied']} applied, {s['flagged']} flagged"
                )
            else:
                lines.append(f"{title}: failed")
        info_dialog(self.gui, "Colophon — done", "\n".join(lines) or "Complete.", show=True)