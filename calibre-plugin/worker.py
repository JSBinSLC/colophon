"""Run Colophon against a Calibre library EPUB and write results back."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from calibre_plugins.colophon.embed import setup_colophon_path


def repair_epub_for_book(db, book_id: int, graph_dir: Path | None = None) -> dict:
    """Export EPUB, run Colophon, replace format in library. Returns summary dict."""
    setup_colophon_path()

    from calibre_plugins.colophon.config import build_pipeline_config, prefs
    from colophon import pipeline

    fmt = "EPUB"
    fmts = db.formats(book_id, index_is_id=True)
    if isinstance(fmts, str):
        fmt_list = [fmts]
    else:
        fmt_list = list(fmts)
    if fmt.lower() not in {f.lower() for f in fmt_list}:
        raise ValueError("Selected book has no EPUB format")

    if graph_dir is None:
        graph_dir = graph_dir_for_book(db, book_id)
    graph_dir.mkdir(parents=True, exist_ok=True)

    config = build_pipeline_config()
    config.output.graph_output_path = graph_dir / "book_graph.json"

    with tempfile.TemporaryDirectory(prefix="colophon_calibre_") as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "source.epub"
        db.new_api.copy_format_to(book_id, fmt, str(src))

        backup_path = None
        if prefs["backup_original"]:
            backup_path = graph_dir / "original.epub"
            shutil.copy2(src, backup_path)

        from calibre_plugins.colophon.host_runner import (
            can_load_ai_deps_in_calibre,
            load_report_json,
            run_pipeline_host,
        )

        report_path = graph_dir / "repair-report.json"
        if can_load_ai_deps_in_calibre():
            report = pipeline.run(src, config, quiet=True)
        else:
            run_pipeline_host(src, config, report_path)
            report = load_report_json(report_path, str(src))

        if report.skipped_reason:
            return {
                "ok": False,
                "skipped": report.skipped_reason,
                "summary": report.summary(),
                "backup_path": str(backup_path) if backup_path else None,
            }

        repaired = src.with_stem(src.stem + ".repaired")
        if not repaired.exists():
            raise RuntimeError("Colophon did not produce a repaired EPUB")

        with open(repaired, "rb") as f:
            db.add_format(book_id, fmt, f, index_is_id=True, notify=False)

        if can_load_ai_deps_in_calibre():
            report.write(report_path)

        return {
            "ok": True,
            "summary": report.summary(),
            "validation": {
                "errors_before": report.validation_errors_before,
                "errors_after": report.validation_errors_after,
                "warnings_before": report.validation_warnings_before,
                "warnings_after": report.validation_warnings_after,
            },
            "backup_path": str(backup_path) if backup_path else None,
            "graph_path": str(graph_dir / "book_graph.json")
            if prefs["persist_graph"]
            else None,
            "report_path": str(report_path),
        }


def graph_dir_for_book(db, book_id: int) -> Path:
    """Return ``<book_folder>/colophon/`` for graph, reports, and backups."""
    path = db.abspath(book_id, index_is_id=True)
    if not path:
        raise ValueError("Could not resolve book path in library")
    return Path(path) / "colophon"