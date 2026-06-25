"""Run Colophon against a Calibre library EPUB and write results back."""
from __future__ import annotations

import tempfile
from pathlib import Path

from calibre_plugins.colophon.embed import setup_colophon_path


def repair_epub_for_book(db, book_id: int) -> dict:
    """Export EPUB, run Colophon, replace format in library. Returns summary dict."""
    setup_colophon_path()

    from calibre_plugins.colophon.book_data import (
        BACKUP_RELPATH,
        GRAPH_RELPATH,
        REPORT_RELPATH,
        copy_extra_to_path,
        has_extra_file,
        migrate_legacy_colophon_folder,
        publish_extra_file,
    )
    from calibre_plugins.colophon.config import build_pipeline_config, prefs
    from calibre_plugins.colophon.host_runner import (
        can_load_ai_deps_in_calibre,
        load_report_json,
        run_pipeline_host,
    )
    from colophon import pipeline

    fmt = "EPUB"
    api = db.new_api
    fmts = db.formats(book_id, index_is_id=True)
    if isinstance(fmts, str):
        fmt_list = [fmts]
    else:
        fmt_list = list(fmts)
    if fmt.lower() not in {f.lower() for f in fmt_list}:
        raise ValueError("Selected book has no EPUB format")

    book_folder = Path(db.abspath(book_id, index_is_id=True))
    migrate_legacy_colophon_folder(api, book_id, book_folder)

    config = build_pipeline_config()

    with tempfile.TemporaryDirectory(prefix="colophon_calibre_") as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "source.epub"
        api.copy_format_to(book_id, fmt, str(src))

        backup_published = False
        if prefs["backup_original"] and not has_extra_file(api, book_id, BACKUP_RELPATH):
            publish_extra_file(api, book_id, BACKUP_RELPATH, src)
            backup_published = True

        graph_tmp = tmp_path / "book_graph.json"
        if prefs["persist_graph"]:
            config.output.graph_output_path = graph_tmp
            if not config.rebuild_graph and has_extra_file(api, book_id, GRAPH_RELPATH):
                copy_extra_to_path(api, book_id, GRAPH_RELPATH, graph_tmp)
        else:
            config.output.graph_output_path = None
            config.output.persist_graph = False

        report_tmp = tmp_path / "repair-report.json"
        if can_load_ai_deps_in_calibre():
            report = pipeline.run(src, config, quiet=True)
            report.write(report_tmp)
        else:
            run_pipeline_host(src, config, report_tmp)
            report = load_report_json(report_tmp, str(src))

        if report.skipped_reason:
            return {
                "ok": False,
                "skipped": report.skipped_reason,
                "summary": report.summary(),
                "backup_path": BACKUP_RELPATH if backup_published else None,
            }

        repaired = src.with_stem(src.stem + ".repaired")
        if not repaired.exists():
            raise RuntimeError("Colophon did not produce a repaired EPUB")

        with open(repaired, "rb") as f:
            db.add_format(book_id, fmt, f, index_is_id=True, notify=False)

        if prefs["persist_graph"] and graph_tmp.exists():
            publish_extra_file(api, book_id, GRAPH_RELPATH, graph_tmp)
        if report_tmp.exists():
            publish_extra_file(api, book_id, REPORT_RELPATH, report_tmp)

        backup_abs = str(book_folder / BACKUP_RELPATH) if has_extra_file(api, book_id, BACKUP_RELPATH) else None
        graph_abs = str(book_folder / GRAPH_RELPATH) if (
            prefs["persist_graph"] and has_extra_file(api, book_id, GRAPH_RELPATH)
        ) else None
        report_abs = str(book_folder / REPORT_RELPATH) if has_extra_file(api, book_id, REPORT_RELPATH) else None

        return {
            "ok": True,
            "summary": report.summary(),
            "validation": {
                "errors_before": report.validation_errors_before,
                "errors_after": report.validation_errors_after,
                "warnings_before": report.validation_warnings_before,
                "warnings_after": report.validation_warnings_after,
            },
            "backup_path": backup_abs,
            "graph_path": graph_abs,
            "report_path": report_abs,
        }


def graph_dir_for_book(db, book_id: int) -> Path:
    """Return the book folder ``data/`` path (for callers that need a directory)."""
    path = db.abspath(book_id, index_is_id=True)
    if not path:
        raise ValueError("Could not resolve book path in library")
    return Path(path) / "data"