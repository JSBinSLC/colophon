from __future__ import annotations

from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from colophon import __version__
from colophon.config import PipelineConfig
from colophon import pipeline

# Load .env from cwd (or any parent) before anything else touches env vars.
load_dotenv()

console = Console()




@click.group()
@click.version_option(__version__)
def main() -> None:
    """Colophon — AI-assisted EPUB repair pipeline."""


def _collect_epubs(inputs: tuple[Path, ...], batch: bool) -> list[Path]:
    """Expand inputs into a list of EPUB files.

    With --batch, any directory is searched recursively for *.epub files.
    This also covers the Windows case where the shell does not expand globs.
    """
    epubs: list[Path] = []
    for item in inputs:
        if item.is_dir():
            if not batch:
                raise click.UsageError(
                    f"'{item}' is a directory. Pass --batch to process all EPUBs inside it."
                )
            epubs.extend(sorted(item.rglob("*.epub")))
        else:
            epubs.append(item)
    return epubs


@main.command()
@click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--batch", is_flag=True, help="Treat directory arguments as folders of EPUBs to repair.")
@click.option("--dry-run", is_flag=True, help="Preview changes without applying them.")
@click.option("--interactive", is_flag=True, help="Pause at low-confidence decisions.")
@click.option("--rebuild-graph", is_flag=True, help="Force semantic graph rebuild.")
@click.option("--llm", "llm_model", default=None, help="LLM model (e.g. anthropic/claude-haiku-4-5).")
@click.option("--api-key", "api_key", default=None, envvar="ANTHROPIC_API_KEY",
              help="Anthropic API key. Prefer setting ANTHROPIC_API_KEY in .env instead.")
@click.option("--ollama-url", "ollama_url", default=None, envvar="COLOPHON_OLLAMA_URL",
              help="Custom Ollama base URL (e.g. http://100.x.x.x:11434).")
@click.option("--num-ctx", "num_ctx", default=None, type=int, envvar="COLOPHON_NUM_CTX",
              help="Ollama context window size in tokens (e.g. 262144).")
@click.option("--report-dir", "report_dir", default=None, type=click.Path(path_type=Path, file_okay=False),
              help="Write each repair report into this directory (default: alongside each EPUB).")
def fix(
    inputs: tuple[Path, ...],
    batch: bool,
    dry_run: bool,
    interactive: bool,
    rebuild_graph: bool,
    llm_model: str | None,
    api_key: str | None,
    ollama_url: str | None,
    num_ctx: int | None,
    report_dir: Path | None,
) -> None:
    """Repair one or more EPUB files."""
    config = PipelineConfig(dry_run=dry_run, interactive=interactive, rebuild_graph=rebuild_graph)
    if llm_model:
        config.llm.model = llm_model
    if api_key:
        config.llm.api_key = api_key
    if ollama_url:
        config.llm.api_base = ollama_url
    if num_ctx:
        config.llm.num_ctx = num_ctx

    epub_files = _collect_epubs(inputs, batch)
    if not epub_files:
        raise click.UsageError("No EPUB files found to process.")

    if report_dir and not dry_run:
        report_dir.mkdir(parents=True, exist_ok=True)

    for epub_path in epub_files:
        console.rule(f"[bold]{epub_path.name}[/bold]")
        report = pipeline.run(epub_path, config)

        if report_dir:
            out_path = report_dir / f"{epub_path.stem}.repair-report.json"
        else:
            out_path = epub_path.with_suffix(".repair-report.json")
        if not dry_run:
            report.write(out_path)

        summary = report.summary()
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_row("[green]Applied[/green]", str(summary["applied"]))
        table.add_row("[yellow]Flagged for review[/yellow]", str(summary["flagged"]))
        table.add_row("[dim]Skipped[/dim]", str(summary["skipped"]))
        if dry_run:
            table.add_row(
                "Validation",
                f"{report.validation_errors_before} errors, "
                f"{report.validation_warnings_before} warnings (before repair)",
            )
        else:
            table.add_row(
                "Validation",
                f"{report.validation_errors_before} -> {report.validation_errors_after} errors, "
                f"{report.validation_warnings_before} -> {report.validation_warnings_after} warnings",
            )
        console.print(table)

        if not dry_run:
            console.print(f"  Report: [dim]{out_path}[/dim]")

    console.print()
