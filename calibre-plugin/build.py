#!/usr/bin/env python3
"""Build colophon_calibre_plugin.zip for installation via Calibre Preferences → Plugins.

Bundles:
  - This plugin's Python files (calibre_plugins.colophon)
  - A vendored copy of the colophon package from the parent repo
  - Pure-Python third-party deps listed in requirements-vendor.txt (optional)

Usage (from repo root):
  python calibre-plugin/build.py

Targets Calibre 9.5+ (matches its embedded Python for vendored wheels).

Install in Calibre:
  Preferences → Plugins → Load plugin from file → select the ZIP
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

_SKIP_NAMES = {
    ".build",
    "build.py",
    "requirements-vendor.txt",
    "__pycache__",
    "_test_import.py",
}

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
OUT = REPO / "dist" / "colophon_calibre_plugin.zip"
PLUGIN_SRC = ROOT
COLOPHON_PKG = REPO / "colophon"
VENDOR_DIR = ROOT / "vendor"
VENDOR_REQ = ROOT / "requirements-vendor.txt"


def _copy_colophon(staging: Path) -> None:
    dest = staging / "colophon"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        COLOPHON_PKG,
        dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
    )


def _pip_executable() -> list[str]:
    """Pick a Python whose ABI matches Calibre's embedded interpreter."""
    calibre_debug = shutil.which("calibre-debug")
    if calibre_debug:
        probe = subprocess.run(
            [calibre_debug, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            check=True,
            capture_output=True,
            text=True,
        )
        py_mm = probe.stdout.strip()
        for candidate in (f"python{py_mm}", f"python3.{py_mm.split('.')[-1]}"):
            path = shutil.which(candidate)
            if path:
                return [path, "-m", "pip"]
        print(
            f"Warning: Calibre uses Python {py_mm} but no matching python{py_mm} found on PATH; "
            f"falling back to {sys.executable}",
        )
    return [sys.executable, "-m", "pip"]


def _vendor_pure_python(staging: Path) -> None:
    if not VENDOR_REQ.exists():
        return
    vendor_target = staging / "vendor"
    vendor_target.mkdir(parents=True, exist_ok=True)
    pip = _pip_executable()
    print(f"Vendoring deps with: {' '.join(pip)}")
    subprocess.run(
        [
            *pip,
            "install",
            "-r",
            str(VENDOR_REQ),
            "--target",
            str(vendor_target),
            "--upgrade",
        ],
        check=True,
    )


def _zip_staging(staging: Path, out_zip: Path) -> None:
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    if out_zip.exists():
        out_zip.unlink()
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(staging.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            zf.write(path, path.relative_to(staging).as_posix())


def main() -> None:
    staging = ROOT / ".build"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()

    for item in PLUGIN_SRC.iterdir():
        if item.name in _SKIP_NAMES:
            continue
        dest = staging / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    _copy_colophon(staging)
    _vendor_pure_python(staging)
    _zip_staging(staging, OUT)
    shutil.rmtree(staging)
    print(f"Built {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()