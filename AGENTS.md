# Agent notes for Colophon

AI-assisted EPUB repair. CLI package in `colophon/`, Calibre 9.5+ interface plugin in `calibre-plugin/`. Design and roadmap live in `SPEC.md`.

## Layout

- `colophon/` — library + `colophon` CLI (`colophon.cli:main`)
- `colophon/stages/` — pipeline stages (unpack → collection → analysis → html → text → chapter → toc → css → repack)
- `colophon/models/` — LLM adapter + planned spaCy fallback
- `calibre-plugin/` — Calibre `InterfaceActionBase` plugin; `build.py` vendors the package into `dist/colophon_calibre_plugin.zip`
- `tests/` — pytest; copyrighted fixture EPUBs are not committed (see `tests/fixtures/README.md`)

## Commands

```bash
pip install -e ".[dev]"
pytest
ruff check .
python calibre-plugin/build.py
```

## Hard rules

- **PyPI:** never tell anyone to `pip install colophon`. That name is a different reserved stub. Install from this git repo with `pip install -e .`.
- **DRM:** detect and skip (`DRM001`). Do not remove DRM, write strippers, or add DeDRM.
- **Font obfuscation is not DRM.** IDPF/Adobe font mangling must remain repairable.
- **Don't commit** `.env`, API keys, `calibre-plugin/vendor/`, or copyrighted `tests/fixtures/*.epub`.
- **Calibre plugin** targets 9.5+. Prefer Calibre's `data/` extra files (`original.epub.orig`, `book_graph.json`, `repair-report.json`), not a sidecar `colophon/` folder.
- **Small diffs.** Match existing style (ruff line length 100, Python 3.11). No drive-by refactors.
- **Verify.** Run the relevant pytest module before claiming a stage fix works.

## Pipeline notes

`colophon.pipeline.run()` is the single entry point. GUI hosts pass `quiet=True`. Interactive review is CLI-only (`interactive=False` in the Calibre plugin).

Stage 1 (semantic graph / NER) is the LLM-heavy step. HTML/CSS/TOC/chapter/font work is deterministic code. Do not route structural repair through the LLM.

## Plugin build

`python calibre-plugin/build.py` copies plugin sources + the `colophon` package + `calibre-plugin/requirements-vendor.txt` into a zip. If vendored native wheels fail inside Calibre, `host_runner.py` falls back to a host Python with this repo on `sys.path`.
