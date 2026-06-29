"""Run Colophon repair on a library book (for calibre-debug -e)."""
from __future__ import annotations

import json
import sys

LIBRARY = "/Users/jbennion/Library/CloudStorage/OneDrive-Personal/Calibre"
BOOK_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 4358

from calibre.db.legacy import LibraryDatabase

from calibre_plugins.colophon.config import prefs
from calibre_plugins.colophon.worker import repair_epub_for_book

print("Plugin prefs:")
print(json.dumps({k: ("***" if "key" in k and v else v) for k, v in dict(prefs).items()}, indent=2))

db = LibraryDatabase(LIBRARY)
meta = db.new_api.get_metadata(BOOK_ID)
title = meta.title
authors = " & ".join(a.replace("|", ",") for a in meta.authors)
print(f"\nRepairing book_id={BOOK_ID}: {title} — {authors}")

result = repair_epub_for_book(db, BOOK_ID)
print(json.dumps(result, indent=2, default=str))