"""Run Colophon against a Calibre library EPUB and write results back."""
from __future__ import annotations

import tempfile
from pathlib import Path

from calibre_plugins.colophon.embed import setup_colophon_path


def repair_epub_for_book(db, book_id: int, graph_dir: Path | None = None) -> dict:
    """Export EPUB, run Colophon, replace format in library. Returns summary dict."""
    setup_colophon_path()

    from calibre_plugins.colophon.config import build_pipeline_config
    from colophon import pipeline

    fmt = "EPUB"
    fmts = db.formats(book_id, index_is_id=True)
    if not fmt.lower() in (f.lower() for f in fmts):
        raise ValueError("Selected book has no EPUB format")

    config = build_pipeline_config()
    if graph_dir is not None:
        graph_dir.mkdir(parents=True, exist_ok=True)
        config.output.graph_output_path = graph_dir / "book_graph.json"

    with tempfile.TemporaryDirectory(prefix="colophon_calibre_") as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "source.epub"
        with open(src, "wb") as f:
            db.format(book_id, fmt, f, index_is_id=True)

        report = pipeline.run(src, config, quiet=True)

        if report.skipped_reason:
            return {
                "ok": False,
                "skipped": report.skipped_reason,
                "summary": report.summary(),
            }

        repaired = src.with_stem(src.stem + ".repaired")
        if not repaired.exists():
            raise RuntimeError("Colophon did not produce a repaired EPUB")

        with open(repaired, "rb") as f:
            db.add_format(book_id, fmt, f, run_hooks=False, index_is_id=True)

        report_path = graph_dir / "repair-report.json" if graph_dir else repaired.with_suffix(".repair-report.json")
        if graph_dir:
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
            "report_path": str(report_path) if report_path else None,
        }


def graph_dir_for_book(db, book_id: int) -> Path:
    """Return ``book_data/colophon/`` for persisting the semantic graph."""
    path = db.abspath(book_id, index_is_id=True)
    if not path:
        raise ValueError("Could not resolve book path in library")
    return Path(path) / "colophon"