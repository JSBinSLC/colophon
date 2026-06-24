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

        # DRM is a hard stop: there is nothing to unpack or repair. Abort the
        # pipeline before extraction so no pointless output file is produced.
        if _gate_on_drm(ctx, result):
            return

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
        _gate_on_drm(ctx, result)


def _gate_on_drm(ctx: dict, result) -> bool:
    """If the validation result flags DRM, mark the run skipped. Returns True
    when DRM was detected (caller should abort)."""
    if any(i.code == "DRM001" for i in result.errors):
        reason = "DRM-protected (encrypted content) - cannot repair"
        ctx["abort_reason"] = reason
        ctx["report"].skipped_reason = reason
        return True
    return False


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
