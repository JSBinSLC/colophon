"""Calibre per-book data folder helpers (``{book}/data/`` extra files)."""
from __future__ import annotations

import shutil
from pathlib import Path

BACKUP_RELPATH = "data/original.epub.orig"
GRAPH_RELPATH = "data/book_graph.json"
REPORT_RELPATH = "data/repair-report.json"

LEGACY_DIR = "colophon"


def has_extra_file(api, book_id: int, relpath: str) -> bool:
    return any(e.relpath == relpath for e in api.list_extra_files(book_id))


def copy_extra_to_path(api, book_id: int, relpath: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as out:
        api.copy_extra_file_to(book_id, relpath, out)


def publish_extra_file(api, book_id: int, relpath: str, src: Path) -> None:
    with open(src, "rb") as stream:
        api.add_extra_files(book_id, {relpath: stream}, replace=True)


def migrate_legacy_colophon_folder(api, book_id: int, book_folder: Path) -> None:
    """Move pre-data-folder Colophon artifacts into Calibre's data/ tree."""
    legacy = book_folder / LEGACY_DIR
    if not legacy.is_dir():
        return
    moves = {
        "original.epub": BACKUP_RELPATH,
        "book_graph.json": GRAPH_RELPATH,
        "repair-report.json": REPORT_RELPATH,
    }
    for name, relpath in moves.items():
        src = legacy / name
        if src.is_file() and not has_extra_file(api, book_id, relpath):
            publish_extra_file(api, book_id, relpath, src)
    stale = [
        e.relpath
        for e in api.list_extra_files(book_id)
        if e.relpath.startswith(f"{LEGACY_DIR}/")
    ]
    if stale:
        api.remove_extra_files(book_id, stale)
    if legacy.is_dir():
        shutil.rmtree(legacy)