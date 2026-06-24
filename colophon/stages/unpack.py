from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from colophon.stages import Stage
from colophon.validator import validate


class UnpackStage(Stage):
    label = "Stage 0 — Unpack & validate"

    def run(self, ctx: dict) -> None:
        epub_path: Path = ctx["epub_path"]

        result = validate(epub_path)
        ctx["validation_before"] = result
        ctx["report"].validation_errors_before = len(result.errors)
        ctx["report"].validation_warnings_before = len(result.warnings)

        tmp = Path(tempfile.mkdtemp(prefix="colophon_"))
        ctx["work_dir"] = tmp

        with zipfile.ZipFile(epub_path) as zf:
            zf.extractall(tmp)

        ctx["epub_version"] = _detect_version(tmp)

    def analyze(self, ctx: dict) -> None:
        epub_path: Path = ctx["epub_path"]
        result = validate(epub_path)
        ctx["validation_before"] = result
        ctx["report"].validation_errors_before = len(result.errors)
        ctx["report"].validation_warnings_before = len(result.warnings)


def _detect_version(work_dir: Path) -> str:
    """Return '2' or '3' based on the OPF package version attribute."""
    from lxml import etree

    container = work_dir / "META-INF" / "container.xml"
    if not container.exists():
        return "unknown"

    root = etree.parse(str(container)).getroot()
    ns = {"cnt": "urn:oasis:names:tc:opendocument:xmlns:container"}
    rootfiles = root.findall(".//cnt:rootfile", ns)
    if not rootfiles:
        return "unknown"

    opf_path = work_dir / rootfiles[0].get("full-path", "")
    if not opf_path.exists():
        return "unknown"

    pkg = etree.parse(str(opf_path)).getroot()
    version = pkg.get("version", "")
    return "3" if version.startswith("3") else "2"
