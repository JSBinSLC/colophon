"""Run Colophon in a host Python when Calibre cannot load vendored native wheels."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def runtime_paths() -> list[Path]:
    """sys.path entries so host Python can import vendored colophon + deps."""
    root = Path(__file__).resolve().parent
    paths = [root]
    vendor = root / "vendor"
    if vendor.is_dir():
        paths.append(vendor)
    # Dev checkout: package lives at <repo>/colophon, not <plugin>/colophon.
    if not (root / "colophon" / "pipeline.py").is_file():
        repo = root.parent
        if (repo / "colophon" / "pipeline.py").is_file():
            paths.insert(0, repo)
    return paths


def host_colophon_repo() -> Path:
    from calibre_plugins.colophon.config import prefs

    if prefs.get("host_colophon_repo"):
        return Path(prefs["host_colophon_repo"])
    return runtime_paths()[0]


def _import_probe_script() -> str:
    inserts = ", ".join(repr(str(p)) for p in runtime_paths())
    return (
        "import sys\n"
        f"for p in ({inserts},):\n"
        "    if p not in sys.path:\n"
        "        sys.path.insert(0, p)\n"
        "import colophon.pipeline, litellm\n"
    )


def find_host_python() -> str:
    """Return a host Python that can import colophon and litellm."""
    exe = probe_host_python()
    if exe:
        return exe
    raise RuntimeError(
        "Calibre cannot load LiteLLM (needed to call Claude/OpenAI/OpenRouter). "
        "Install it in a system Python, then restart Calibre:\n"
        "  python3 -m pip install litellm\n"
        "The API key is not enough on its own — LiteLLM is the client that sends it."
    )


def probe_host_python() -> str | None:
    """Like find_host_python, but returns None instead of raising."""
    from calibre_plugins.colophon.config import prefs

    candidates: list[str] = []
    if prefs.get("host_python"):
        candidates.append(prefs["host_python"])
    for name in ("python3.14", "python3.13", "python3.12", "python3", "python"):
        path = shutil.which(name)
        if path:
            candidates.append(path)

    seen: set[str] = set()
    script = _import_probe_script()
    for exe in candidates:
        if not exe or exe in seen:
            continue
        seen.add(exe)
        try:
            subprocess.run(
                [exe, "-c", script],
                check=True,
                capture_output=True,
                timeout=20,
                **_subprocess_kwargs(),
            )
            return exe
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            continue
    return None


def can_load_ai_deps_in_calibre() -> bool:
    """True when vendored pydantic_core loads inside Calibre's interpreter."""
    try:
        import litellm  # noqa: F401
        import pydantic_core._pydantic_core  # noqa: F401
    except Exception:
        return False
    return True


_CREATE_NO_WINDOW = 0x08000000


def _subprocess_kwargs(is_windows: bool | None = None) -> dict:
    """Extra subprocess.run kwargs to keep Windows from flashing a console."""
    if is_windows is None:
        is_windows = os.name == "nt"
    return {"creationflags": _CREATE_NO_WINDOW} if is_windows else {}


def run_pipeline_host(epub_path: Path, config, report_path: Path) -> None:
    """Execute pipeline.run in a subprocess using host Python."""
    py = find_host_python()
    path_inserts = ", ".join(repr(str(p)) for p in runtime_paths())

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
for p in ({path_inserts},):
    if p not in sys.path:
        sys.path.insert(0, p)
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
    subprocess.run(
        [py, "-c", script],
        check=True,
        env=env,
        capture_output=True,
        **_subprocess_kwargs(),
    )


def hydrate_report(data: dict, source_epub: str):
    """Build a RepairReport from parsed repair-report.json data."""
    from colophon.report import ChangeStatus, Confidence, RepairChange, RepairReport

    report = RepairReport(source_epub=source_epub)
    report.skipped_reason = data.get("skipped_reason")
    val = data.get("validation", {})
    report.validation_errors_before = val.get("errors_before", 0)
    report.validation_errors_after = val.get("errors_after", 0)
    report.validation_warnings_before = val.get("warnings_before", 0)
    report.validation_warnings_after = val.get("warnings_after", 0)

    for row in data.get("changes", []):
        stage = row.get("stage")
        description = row.get("description")
        confidence = row.get("confidence")
        status = row.get("status")
        if not (stage and description and confidence and status):
            continue
        report.changes.append(
            RepairChange(
                stage=stage,
                description=description,
                confidence=Confidence(confidence),
                status=ChangeStatus(status),
                location=row.get("location"),
                original=row.get("original"),
                replacement=row.get("replacement"),
            )
        )
    return report


def load_report_json(report_path: Path, source_epub: str):
    from colophon.report import RepairReport

    if not report_path.exists():
        return RepairReport(source_epub=source_epub)
    data = json.loads(report_path.read_text(encoding="utf-8"))
    return hydrate_report(data, source_epub)
