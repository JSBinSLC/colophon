from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from colophon.stages import Stage
from colophon.validator import validate


class RepackStage(Stage):
    label = "Stage 7 — Repack & final validation"

    def run(self, ctx: dict) -> None:
        work_dir: Path = ctx["work_dir"]
        epub_path: Path = ctx["epub_path"]

        output_path = epub_path.with_stem(epub_path.stem + ".repaired")
        _pack_epub(work_dir, output_path)
        ctx["output_epub"] = output_path

        result = validate(output_path)
        ctx["validation_after"] = result
        ctx["report"].validation_errors_after = len(result.errors)
        ctx["report"].validation_warnings_after = len(result.warnings)

        shutil.rmtree(work_dir, ignore_errors=True)

    def analyze(self, ctx: dict) -> None:
        pass


def _pack_epub(source_dir: Path, output_path: Path) -> None:
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # mimetype must be first and uncompressed per EPUB spec
        mimetype = source_dir / "mimetype"
        if mimetype.exists():
            zf.write(mimetype, "mimetype", compress_type=zipfile.ZIP_STORED)

        for file in sorted(source_dir.rglob("*")):
            if file.is_file() and file.name != "mimetype":
                zf.write(file, file.relative_to(source_dir))
