# Colophon

> *"Because when you want to read a book, you want to read a book — not be a copy editor."*

Your one-stop EPUB fixer with AI smarts. Fixes broken navigation, OCR artifacts, header/footer bleed, inconsistent proper nouns, poor HTML structure, CSS disorder, broken font obfuscation, and more — in a single command.

```
colophon fix book.epub
```

## Status

Active development (v0.1). Working stages:

| Stage | Status | What it does |
|---|---|---|
| Stage 0 — Unpack & Validate | ✅ | ZIP extraction, built-in EPUB validator, DRM gate |
| Stage 1 — Semantic Graph | ✅ | NER via LLM (Anthropic/OpenAI/OpenRouter/Ollama), variant clustering, concurrent chunking, graph cache |
| Stage 5 — TOC Rebuild | ✅ | Generates toc.ncx + nav.xhtml from in-document headings; fixes NCX001/NCX005/NCX008/NAV003/NAV004 |
| Stage 7 — Repack | ✅ | Correct mimetype ordering, re-validation, repair report |
| Stages 2–4, 6 | Planned | HTML repair, text cleanup, chapter detection, CSS sanitization |
| Font obfuscation re-keying | Planned (v0.5) | Detects IDPF/Adobe-obfuscated fonts; re-keys them to the canonical UID so repaired EPUBs don't break embedded fonts |

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

# Repair with a specific LLM backend (Anthropic, OpenAI, OpenRouter, or Ollama)
colophon fix book.epub --llm anthropic/claude-haiku-4-5
colophon fix book.epub --llm openrouter/google/gemini-2.5-flash-lite

# Speed up a large book: analyze the default-sized chunks in parallel
colophon fix book.epub --llm openrouter/google/gemini-2.5-flash-lite --concurrency 8

# Repair every EPUB in a folder (recursively)
colophon fix ./my-library --batch

# Write all reports into one directory instead of alongside each EPUB
colophon fix ./my-library --batch --report-dir ./reports
```

### Key options

| Flag | Env var | Default | Purpose |
|---|---|---|---|
| `--llm` | `COLOPHON_LLM_MODEL` | `anthropic/claude-haiku-4-5` | Provider/model string |
| `--chunk-chars` | `COLOPHON_MAX_CHUNK_CHARS` | 32000 | Chars per Stage 1 chunk. The default extracts well; raising it cuts API calls but risks hitting the model's output-token ceiling (truncating the graph) — see note below |
| `--concurrency` | `COLOPHON_CONCURRENCY` | 4 | Chunks analyzed in parallel (use 1 for local Ollama) |
| `--use-batch` | — | off | OpenAI Batch API (~50% cheaper, async); `openai/` models only |
| `--rebuild-graph` | — | off | Force a fresh semantic graph instead of reusing the cache |

API keys come from `.env` (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`) — see [.env.example](.env.example).

> **A note on chunk size.** Bigger chunks are *not* better. Each chunk's entity list must fit inside the model's max output tokens; a whole-novel single chunk routinely overflows that ceiling and the graph is truncated mid-extraction. (Dogfooding *Brave New World* through Gemini 2.5 Flash Lite: the default 32K chunking found 20 characters, 10 places, 20 invented terms; forcing one 380K-char chunk hit the 65K-token output limit — partly via a degenerate repetition loop — and salvaged only 2 characters.) To go faster on a big book, raise `--concurrency`, not `--chunk-chars`.

## Configuration

Create a `colophon.toml` in your project directory or `~/.config/colophon/config.toml`:

```toml
[llm]
model = "ollama/mistral"   # default — no API key required
temperature = 0.0          # deterministic extraction (reproducible graph)
max_concurrency = 4        # chunks analyzed in parallel
# max_chunk_chars = 600000 # send a whole novel in one shot on big-context models
# max_output_tokens = 0    # 0/unset = use the model's documented max

[hints]
character_names = ["T'Pring", "McCoy", "Spock"]

[output]
persist_graph = true       # save book_graph alongside EPUB for reuse
```

The graph cache is keyed on `(file checksum, model, schema version)`, so switching `--llm` automatically rebuilds the graph rather than reusing another model's output.

## Contributing

See [SPEC.md](SPEC.md) for architecture. Each pipeline stage is a self-contained module in `colophon/stages/` — pick one up, write tests against the fixture EPUBs in `tests/fixtures/`, and submit a PR.

## License

MIT
