from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

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

console = Console()


def run(epub_path: Path, config: PipelineConfig) -> RepairReport:
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

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        ctx: dict = {"epub_path": epub_path, "config": config, "report": report}

        for stage in stages:
            task = progress.add_task(stage.label, total=None)
            if not config.dry_run:
                stage.run(ctx)
            else:
                stage.analyze(ctx)
            progress.remove_task(task)
            # A stage (e.g. unpack on a DRM file) can abort the whole run.
            if ctx.get("abort_reason"):
                break

        if not config.dry_run and config.interactive:
            review_flagged_changes(ctx)

    return report
