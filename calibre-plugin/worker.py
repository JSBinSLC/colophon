"""Run Colophon against a Calibre library EPUB and write results back."""
from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

from calibre_plugins.colophon.embed import setup_colophon_path


def repair_epub_for_book(db, book_id: int, *, rebuild_graph: bool | None = None) -> dict:
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
        fmt_list = list(fmts) if fmts else []
    if fmt.lower() not in {f.lower() for f in fmt_list}:
        raise ValueError("Selected book has no EPUB format")

    book_folder = Path(db.abspath(book_id, index_is_id=True))
    migrate_legacy_colophon_folder(api, book_id, book_folder)

    config = build_pipeline_config()
    if rebuild_graph is not None:
        config.rebuild_graph = rebuild_graph

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
        # ZIP vendors Colophon. Host Python is only for AI when Calibre cannot
        # load LiteLLM: an API key, or an explicit host_colophon_repo.
        want_ai = bool(config.llm.resolved_api_key()) or bool(prefs.get("host_colophon_repo"))
        if can_load_ai_deps_in_calibre():
            report = pipeline.run(src, config, quiet=True)
            report.write(report_tmp)
        elif want_ai:
            try:
                run_pipeline_host(src, config, report_tmp)
                report = load_report_json(report_tmp, str(src))
            except Exception:
                report = pipeline.run(src, config, quiet=True)
                report.write(report_tmp)
        else:
            report = pipeline.run(src, config, quiet=True)
            report.write(report_tmp)

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

        backup_abs = (
            str(book_folder / BACKUP_RELPATH)
            if has_extra_file(api, book_id, BACKUP_RELPATH)
            else None
        )
        graph_abs = (
            str(book_folder / GRAPH_RELPATH)
            if (prefs["persist_graph"] and has_extra_file(api, book_id, GRAPH_RELPATH))
            else None
        )
        report_abs = (
            str(book_folder / REPORT_RELPATH)
            if has_extra_file(api, book_id, REPORT_RELPATH)
            else None
        )

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


def restore_original_epub(db, book_id: int) -> None:
    """Replace the library EPUB with data/original.epub.orig."""
    setup_colophon_path()
    from calibre_plugins.colophon.book_data import BACKUP_RELPATH, copy_extra_to_path, has_extra_file

    api = db.new_api
    if not has_extra_file(api, book_id, BACKUP_RELPATH):
        raise ValueError("No original.epub.orig backup for this book")
    with tempfile.TemporaryDirectory(prefix="colophon_restore_") as tmp:
        dest = Path(tmp) / "original.epub"
        copy_extra_to_path(api, book_id, BACKUP_RELPATH, dest)
        with open(dest, "rb") as f:
            db.add_format(book_id, "EPUB", f, index_is_id=True, notify=False)


def restore_original_and_repair(db, book_id: int) -> dict:
    """Restore the pre-Colophon EPUB, then repair it with a fresh graph."""
    restore_original_epub(db, book_id)
    return repair_epub_for_book(db, book_id, rebuild_graph=True)


def graph_dir_for_book(db, book_id: int) -> Path:
    """Return the book folder ``data/`` path (for callers that need a directory)."""
    path = db.abspath(book_id, index_is_id=True)
    if not path:
        raise ValueError("Could not resolve book path in library")
    return Path(path) / "data"


def apply_review_actions_for_book(db, book_id: int, actions: list) -> dict:
    """Unpack current EPUB, apply ReviewActions one-by-one, write EPUB + report.

    `actions` is a list of ReviewAction or (index, action_str) pairs.
    Apply one action at a time so a ValueError on one row does not roll back
    earlier successes. If any HTML mutation succeeded, repack and add_format.
    Always rewrite repair-report.json if the report dict changed (including
    reject-only, which does not edit HTML).

    Returns:
      {
        "ok": bool,  # True if at least one action succeeded
        "report": dict,  # latest report
        "errors": list[str],  # per-failed-row messages
        "succeeded": int,
        "failed": int,
      }
    """
    setup_colophon_path()

    from calibre_plugins.colophon.book_data import (
        REPORT_RELPATH,
        copy_extra_to_path,
        has_extra_file,
        publish_extra_file,
    )

    from colophon.review import ReviewAction, apply_actions
    from colophon.stages.repack import _pack_epub

    fmt = "EPUB"
    api = db.new_api
    fmts = db.formats(book_id, index_is_id=True)
    if isinstance(fmts, str):
        fmt_list = [fmts]
    else:
        fmt_list = list(fmts) if fmts else []
    if fmt.lower() not in {f.lower() for f in fmt_list}:
        raise ValueError("Selected book has no EPUB format")

    if not has_extra_file(api, book_id, REPORT_RELPATH):
        raise ValueError("No repair report found for selected book")

    review_actions: list[ReviewAction] = []
    for item in actions:
        if isinstance(item, ReviewAction):
            review_actions.append(item)
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            review_actions.append(ReviewAction(index=int(item[0]), action=str(item[1])))
        elif isinstance(item, dict):
            review_actions.append(
                ReviewAction(index=int(item["index"]), action=str(item["action"]))
            )
        else:
            raise TypeError(f"Invalid action item: {item!r}")

    with tempfile.TemporaryDirectory(prefix="colophon_calibre_review_") as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "current.epub"
        api.copy_format_to(book_id, fmt, str(src))

        work_dir = tmp_path / "work"
        work_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(src, "r") as zf:
            zf.extractall(work_dir)

        report_tmp = tmp_path / "repair-report.json"
        copy_extra_to_path(api, book_id, REPORT_RELPATH, report_tmp)
        with open(report_tmp, encoding="utf-8") as f:
            report = json.load(f)

        errors: list[str] = []
        succeeded = 0
        mutated_html = False

        for act in review_actions:
            try:
                report = apply_actions(work_dir, report, [act])
                succeeded += 1
                if act.action in ("apply", "revert"):
                    mutated_html = True
            except ValueError as exc:
                errors.append(f"Change #{act.index + 1}: {exc}")
            except Exception as exc:
                errors.append(f"Change #{act.index + 1}: {exc}")

        if succeeded > 0:
            if mutated_html:
                repacked = tmp_path / "repacked.epub"
                _pack_epub(work_dir, repacked)
                with open(repacked, "rb") as f:
                    db.add_format(book_id, fmt, f, index_is_id=True, notify=False)

            with open(report_tmp, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
            publish_extra_file(api, book_id, REPORT_RELPATH, report_tmp)

        return {
            "ok": succeeded > 0,
            "report": report,
            "errors": errors,
            "succeeded": succeeded,
            "failed": len(errors),
        }