from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from colophon.config import PipelineConfig
from colophon.report import RepairReport
from colophon.interactive import review_flagged_changes
from colophon.stages.unpack import UnpackStage
from colophon.stages.collection import CollectionDetectStage
from colophon.stages.analysis import AnalysisStage
from colophon.stages.html_repair import HtmlRepairStage
from colophon.stages.text_cleanup import TextCleanupStage
from colophon.stages.chapter_detect import ChapterDetectStage
from colophon.stages.toc_rebuild import TocRebuildStage
from colophon.stages.css_sanitize import CssSanitizeStage
from colophon.stages.repack import RepackStage


def run(
    epub_path: Path,
    config: PipelineConfig,
    *,
    quiet: bool = False,
    on_stage: Callable[[str], None] | None = None,
) -> RepairReport:
    """Run the repair pipeline.

    Args:
        quiet: Skip Rich terminal progress (use from GUI hosts like Calibre).
        on_stage: Optional callback invoked with each stage label as it runs.
    """
    report = RepairReport(source_epub=str(epub_path))

    stages = [
        UnpackStage(),
        CollectionDetectStage(),
        AnalysisStage(),
        HtmlRepairStage(),
        TextCleanupStage(),
        ChapterDetectStage(),
        TocRebuildStage(),
        CssSanitizeStage(),
        RepackStage(),
    ]

    ctx: dict = {"epub_path": epub_path, "config": config, "report": report}

    def _run_one(stage) -> bool:
        """Run a single stage. Returns False if the pipeline should abort."""
        if on_stage is not None:
            on_stage(stage.label)
        if not config.dry_run:
            stage.run(ctx)
        else:
            stage.analyze(ctx)
        return not ctx.get("abort_reason")

    if quiet:
        for stage in stages:
            if not _run_one(stage):
                break
        if not config.dry_run and config.interactive:
            review_flagged_changes(ctx)
    else:
        from rich.console import Console
        from rich.progress import Progress, SpinnerColumn, TextColumn

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=Console(),
            transient=True,
        ) as progress:
            for stage in stages:
                task = progress.add_task(stage.label, total=None)
                if not _run_one(stage):
                    progress.remove_task(task)
                    break
                progress.remove_task(task)
            if not config.dry_run and config.interactive:
                review_flagged_changes(ctx)

    return report