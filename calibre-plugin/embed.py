"""Make vendored Colophon importable inside Calibre's plugin host."""
from __future__ import annotations

import sys
from pathlib import Path


def plugin_root() -> Path:
    """Directory containing this plugin's files (inside the ZIP or dev tree)."""
    return Path(__file__).resolve().parent


def setup_colophon_path() -> None:
    """Prepend vendored ``colophon`` and pure-Python deps to sys.path."""
    root = plugin_root()
    paths: list[Path] = [root / "vendor", root]

    # Built ZIP copies the package to ``<plugin>/colophon/``. In a dev checkout the
    # same package lives at ``<repo>/colophon/`` — add the repo root to sys.path.
    vendored_pkg = root / "colophon"
    if not (vendored_pkg / "__init__.py").is_file():
        repo_root = root.parent
        if (repo_root / "colophon" / "__init__.py").is_file():
            paths.insert(0, repo_root)

    for path in paths:
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)