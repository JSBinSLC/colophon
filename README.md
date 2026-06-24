# Colophon

> *"Because when you want to read a book, you want to read a book — not be a copy editor."*

AI-assisted EPUB repair pipeline. Fixes broken navigation, OCR artifacts, header/footer bleed, inconsistent proper nouns, poor HTML structure, CSS disorder, and more — in a single command.

```
colophon fix book.epub
```

## Status

Active development (v0.1). Working stages:

| Stage | Status | What it does |
|---|---|---|
| Stage 0 — Unpack & Validate | ✅ | ZIP extraction, built-in EPUB validator, DRM gate |
| Stage 1 — Semantic Graph | ✅ | NER via LLM (Anthropic/OpenAI/Ollama), variant clustering, graph cache |
| Stage 5 — TOC Rebuild | ✅ | Generates toc.ncx + nav.xhtml from in-document headings; fixes NCX001/NCX005/NCX008/NAV003/NAV004 |
| Stage 7 — Repack | ✅ | Correct mimetype ordering, re-validation, repair report |
| Stages 2–4, 6 | Planned | HTML repair, text cleanup, chapter detection, CSS sanitization |

See [SPEC.md](SPEC.md) for full design and roadmap.

## Prerequisites

- Python 3.11+

Colophon has no external system dependencies. EPUB validation is handled by a built-in pure-Python validator — no Java, no epubcheck required.

## Installation

```bash
pip install colophon
```

For local model support (no API key required):

```bash
# Install Ollama from https://ollama.com, then:
ollama pull mistral
```

## Quick Start

```bash
# Repair an EPUB with default settings
colophon fix book.epub

# Preview changes without applying them
colophon fix book.epub --dry-run

# Repair with a specific LLM backend
colophon fix book.epub --llm anthropic/claude-haiku-4-5

# Repair every EPUB in a folder (recursively)
colophon fix ./my-library --batch

# Write all reports into one directory instead of alongside each EPUB
colophon fix ./my-library --batch --report-dir ./reports
```

## Configuration

Create a `colophon.toml` in your project directory or `~/.config/colophon/config.toml`:

```toml
[llm]
model = "ollama/mistral"   # default — no API key required

[hints]
character_names = ["T'Pring", "McCoy", "Spock"]

[output]
persist_graph = true       # save book_graph alongside EPUB for reuse
```

## Contributing

See [SPEC.md](SPEC.md) for architecture. Each pipeline stage is a self-contained module in `colophon/stages/` — pick one up, write tests against the fixture EPUBs in `tests/fixtures/`, and submit a PR.

## License

MIT
