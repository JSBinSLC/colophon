# Agent notes for Colophon

AI-assisted EPUB repair. CLI package in `colophon/`. Design and roadmap live in `SPEC.md`. The Calibre plugin source is on the `calibre-plugin-alpha` branch; installable zips are on GitHub Releases.

## Layout

- `colophon/` — library + `colophon` CLI (`colophon.cli:main`)
- `colophon/stages/` — pipeline stages (unpack → collection → analysis → html → text → chapter → toc → css → repack)
- `colophon/models/` — LLM adapter + planned spaCy fallback
- `tests/` — pytest; copyrighted fixture EPUBs are not committed (see `tests/fixtures/README.md`)

## Commands

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

## Hard rules

- **PyPI:** never tell anyone to `pip install colophon`. That name is a different reserved stub. Install from this git repo with `pip install -e .`.
- **DRM:** detect and skip (`DRM001`). Do not remove DRM, write strippers, or add DeDRM.
- **Font obfuscation is not DRM.** IDPF/Adobe font mangling must remain repairable.
- **Don't commit** `.env`, API keys, or copyrighted `tests/fixtures/*.epub`.
- **Small diffs.** Match existing style (ruff line length 100, Python 3.11). No drive-by refactors.
- **Verify.** Run the relevant pytest module before claiming a stage fix works.

## Pipeline notes

`colophon.pipeline.run()` is the single entry point. GUI hosts pass `quiet=True`. Interactive review is CLI-only.

Stage 1 (semantic graph / NER) is the LLM-heavy step. HTML/CSS/TOC/chapter/font work is deterministic code. Do not route structural repair through the LLM.
