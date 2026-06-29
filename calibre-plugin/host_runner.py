"""Run Colophon in a host Python when Calibre cannot load vendored native wheels."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def find_host_python() -> str:
    """Return a Python on the host that can import colophon and litellm."""
    from calibre_plugins.colophon.config import prefs

    candidates: list[str] = []
    if prefs.get("host_python"):
        candidates.append(prefs["host_python"])
    for name in ("python3.14", "python3", "python"):
        path = shutil.which(name)
        if path:
            candidates.append(path)

    seen: set[str] = set()
    for exe in candidates:
        if not exe or exe in seen:
            continue
        seen.add(exe)
        repo = host_colophon_repo()
        try:
            subprocess.run(
                [exe, "-c", f"import sys; sys.path.insert(0,{str(repo)!r}); import colophon.pipeline, litellm"],
                check=True,
                capture_output=True,
                timeout=20,
            )
            return exe
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            continue
    raise RuntimeError(
        "Calibre cannot load the plugin's AI dependencies on this platform. "
        "Install Colophon in a host Python (pip install -e /path/to/colophon) "
        "and set host_colophon_repo in plugin preferences."
    )


def host_colophon_repo() -> Path:
    from calibre_plugins.colophon.config import prefs

    if prefs.get("host_colophon_repo"):
        return Path(prefs["host_colophon_repo"])
    plugin = Path(__file__).resolve().parent
    dev_repo = plugin.parent
    if (dev_repo / "colophon" / "pipeline.py").is_file():
        return dev_repo
    raise RuntimeError(
        "Set host_colophon_repo in plugin preferences to your Colophon git checkout."
    )


def can_load_ai_deps_in_calibre() -> bool:
    """True when vendored pydantic_core loads inside Calibre's interpreter."""
    try:
        import pydantic_core._pydantic_core  # noqa: F401
        import litellm  # noqa: F401
    except Exception:
        return False
    return True


def run_pipeline_host(epub_path: Path, config, report_path: Path) -> None:
    """Execute pipeline.run in a subprocess using host Python."""
    py = find_host_python()
    repo = host_colophon_repo()

    env = os.environ.copy()
    key = config.llm.resolved_api_key()
    if key:
        if config.llm.model.startswith("openrouter/"):
            env["OPENROUTER_API_KEY"] = key
        elif config.llm.model.startswith("anthropic/"):
            env["ANTHROPIC_API_KEY"] = key
        elif config.llm.model.startswith("openai/"):
            env["OPENAI_API_KEY"] = key

    graph_path = config.output.graph_output_path
    script = f"""
import sys
sys.path.insert(0, {str(repo)!r})
from pathlib import Path
from colophon.config import LLMConfig, OutputConfig, PipelineConfig
from colophon import pipeline

llm = LLMConfig(
    model={config.llm.model!r},
    api_key={config.llm.api_key!r},
    reconcile={config.llm.reconcile!r},
    max_concurrency={config.llm.max_concurrency!r},
)
output = OutputConfig(
    persist_graph={config.output.persist_graph!r},
    graph_output_path={str(graph_path) if graph_path else None!r},
)
cfg = PipelineConfig(
    llm=llm,
    output=output,
    rebuild_graph={config.rebuild_graph!r},
    dry_run={config.dry_run!r},
    interactive=False,
)
if cfg.output.graph_output_path:
    cfg.output.graph_output_path = Path(cfg.output.graph_output_path)
report = pipeline.run(Path({str(epub_path)!r}), cfg, quiet=True)
report.write(Path({str(report_path)!r}))
"""
    subprocess.run([py, "-c", script], check=True, env=env)


def load_report_json(report_path: Path, source_epub: str):
    from colophon.report import RepairReport

    report = RepairReport(source_epub=source_epub)
    if not report_path.exists():
        return report
    data = json.loads(report_path.read_text(encoding="utf-8"))
    report.skipped_reason = data.get("skipped_reason")
    val = data.get("validation", {})
    report.validation_errors_before = val.get("errors_before", 0)
    report.validation_errors_after = val.get("errors_after", 0)
    report.validation_warnings_before = val.get("warnings_before", 0)
    report.validation_warnings_after = val.get("warnings_after", 0)
    return report