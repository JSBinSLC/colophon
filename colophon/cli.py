from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from colophon import __version__
from colophon.config import PipelineConfig
from colophon import pipeline

console = Console()




@click.group()
@click.version_option(__version__)
def main() -> None:
    """Colophon — AI-assisted EPUB repair pipeline."""


@main.command()
@click.argument("epub_files", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--dry-run", is_flag=True, help="Preview changes without applying them.")
@click.option("--interactive", is_flag=True, help="Pause at low-confidence decisions.")
@click.option("--rebuild-graph", is_flag=True, help="Force semantic graph rebuild.")
@click.option("--llm", "llm_model", default=None, help="LLM model (e.g. ollama/mistral).")
@click.option("--report", "report_path", default=None, type=click.Path(path_type=Path),
              help="Write repair report to this path (default: <epub>.repair-report.json).")
def fix(
    epub_files: tuple[Path, ...],
    dry_run: bool,
    interactive: bool,
    rebuild_graph: bool,
    llm_model: str | None,
    report_path: Path | None,
) -> None:
    """Repair one or more EPUB files."""
    config = PipelineConfig(dry_run=dry_run, interactive=interactive, rebuild_graph=rebuild_graph)
    if llm_model:
        config.llm.model = llm_model

    for epub_path in epub_files:
        console.rule(f"[bold]{epub_path.name}[/bold]")
        report = pipeline.run(epub_path, config)

        out_path = report_path or epub_path.with_suffix(".repair-report.json")
        if not dry_run:
            report.write(out_path)

        summary = report.summary()
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_row("[green]Applied[/green]", str(summary["applied"]))
        table.add_row("[yellow]Flagged for review[/yellow]", str(summary["flagged"]))
        table.add_row("[dim]Skipped[/dim]", str(summary["skipped"]))
        console.print(table)

        if not dry_run:
            console.print(f"  Report: [dim]{out_path}[/dim]")

    console.print()
