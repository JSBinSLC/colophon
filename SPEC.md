# Colophon — AI-Assisted EPUB Repair Pipeline

*"Because when you want to read a book, you want to read a book — not be a copy editor."*
*"Because even copy editors get tired and miss things."*
*"Your one-stop shop for EPUB correction and repair"
---

## Problem Statement

EPUB files that originate from scanned books, OCR workflows, or poorly exported word processors share a predictable set of defects — and no existing tool fixes all of them:

- **Broken navigation** — missing or malformed TOC, spine out of order, nav.xhtml absent
- **OCR artifacts** — ligature errors (`ﬁ` instead of `fi`), hard hyphens mid-word (`Mc-Coy`, `re-\nmove`), caret noise, garbled diacritics
- **Header/footer bleed** — running page headers and footers (chapter titles, page numbers) captured as body text during OCR, disrupting flow and polluting chapter content
- **Missing structural markers** — dinkuses (`* * *`) and scene-break characters dropped by OCR, causing jarring unannounced scene shifts
- **Inconsistent proper nouns** — bespoke names, places, and terms (especially in genre fiction) rendered differently across the same document (`T'Pring`, `TPring`, `T-Pring`)
- **Lost formatting signals** — italics used for thought, emphasis, or foreign words silently dropped
- **Poor HTML structure** — entire books in one HTML file, headings replaced with bold spans, no semantic chapter markers
- **CSS disorder** — inline styles overriding everything, hardcoded pixel sizes, margins that break on small screens
- **Page numbering failures** — `epub:type="pagebreak"` markers missing, broken, or rendering as visible body text; `page-list` nav absent or misaligned
- **Container violations** — malformed `content.opf`, wrong `mimetype` ordering, missing media types
- **Format version drift** — EPUB 2 files that work nowhere modern, EPUB 3 files that break EPUB 2-only readers

Existing tools each address a slice of this:

| Tool | Structural | OCR/Text | Proper Nouns | Header/Footer | Page Numbers | AI | CLI |
|---|---|---|---|---|---|---|---|
| Sigil | ✓ manual | Partial | ✗ | ✗ | ✗ | ✗ | ✗ |
| Calibre | Partial | ✗ | ✗ | ✗ | ✗ | ✗ | Partial |
| EpubDoctor | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |
| epubrepairtool | Partial | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |
| **Colophon** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

Colophon is not reinventing the wheel. It wraps and orchestrates existing tools while adding an AI/NLP layer — particularly a **semantic knowledge graph** — that none of them have and that modern AI tools like LLMs have gotten really good at.

---

## The Core Differentiator: Semantic Book Graph

The feature that makes Colophon more than a glorified linter is that it builds an internal semantic model of the book during analysis, before making any changes.

This graph captures:
- **Named entities** — characters, places, organizations, bespoke invented terms (extracted via NER)
- **Occurrence frequency and distribution** — how often each entity appears, in which sections
- **Variant spellings** — all observed forms of what appears to be the same entity (`T'Pring`, `TPring`, `T-Pring`)
- **Chapter/section boundaries** — inferred from headings, dinkuses, topic shifts, header/footer patterns
- **Structural landmarks** — TOC entries, spine order, page break markers

This graph drives repair decisions:
- Proper noun variants get resolved to the **most frequent form** (or flagged for user confirmation if frequency is a tie). If we can't be certain, we're *consistently* wrong — `TPring` everywhere beats `T'Pring` in chapter 3 and `TPring` everywhere else.
- Hyphenated names at line breaks (`Mc-\nCoy`) are caught because `McCoy` is already a known entity in the graph, not just via lexical dictionary lookup.
- Header/footer artifacts are detected partly because the graph knows chapter titles — a line that matches a known chapter title appearing mid-paragraph is almost certainly a running header.
- Dinkus detection is informed by topic/entity shift analysis — if entities and topics suddenly change without a structural marker, that's a candidate scene break.

This is not just a dumb spell checker. Your EPUB probably already passed a spell check. This is contextual, structure-conscious, book-aware reasoning with consistency, readability, comprehensibility at the forefront. Using machine tools to make EPUB reading more enjoyable and less distracting for humans, especially us OCD humans.

---

## Pipeline Architecture

```
Input EPUB
    │
    ▼
[Stage 0] Unpack & Validate
    • Extract to temp directory
    • Run Colophon's built-in pure-Python EPUB validator (validator.py), capture violations
    • Normalize container structure (mimetype, META-INF/container.xml)
    • Detect EPUB version (2 or 3), flag for optional upgrade
    │
    ▼
[Stage 1] Analysis — Build Semantic Graph  ◄── AI layer
    • Named entity extraction (NER via spaCy or LLM)
    • Variant spelling clustering
    • Header/footer pattern detection (repeated strings near page boundaries)
    • Chapter boundary candidates (headings, dinkus patterns, topic shift)
    • Page number marker inventory (existing epub:type="pagebreak" audit)
    • Output: book_graph.json (written to temp dir; stages 2–4 read it at startup to drive repair decisions)
    │
    ▼
[Stage 2] HTML Structural Repair
    • BeautifulSoup / html5lib parse each content document
    • Remove inline styles, flatten redundant spans
    • Restore semantic tags (h1–h6, p, em, strong)
    • Fix malformed nesting
    • Detect and flag (or remove) header/footer artifact lines
    │
    ▼
[Stage 3] Text Cleanup  ◄── AI layer
    • Ligature normalization (Unicode + regex)
    • Hard hyphen resolution — dictionary-backed AND graph-backed (proper nouns)
    • Hard carriage return removal in mid-sentence line breaks
    • OCR noise removal (caret artifacts, stray characters)
    • Proper noun consistency pass (apply canonical forms from graph)
    • Whitespace and paragraph normalization
    • Dinkus recovery — insert <hr epub:type="separator"/> at detected scene breaks
    • Flag missing italics candidates (thought attribution, foreign phrases) — human review
      Detection heuristics: (a) lines beginning with attribution verbs followed by direct speech without dialogue punctuation ("she thought", "he wondered", "I realized"); (b) short foreign-language phrases detectable via langdetect against the book's primary language; (c) titles of works (books, ships, films) matched against a known-titles list; (d) LLM pass as a fallback for ambiguous cases — all flagged as low-confidence, never auto-applied
    │
    ▼
[Stage 4] Chapter Detection & Splitting  ◄── AI layer
    • Heading-based detection (h1/h2 tags, ALL-CAPS lines)
    • Semantic cues ("Chapter", "Part", roman numerals, ordinals)
    • Graph-informed: use entity/topic shift data from Stage 1
    • Split single-file books into per-chapter HTML files
    │
    ▼
[Stage 5] TOC & Spine Reconstruction
    • Generate toc.ncx (EPUB 2 compatibility)
    • Generate nav.xhtml (EPUB 3), including page-list nav
    • Rebuild content.opf spine and manifest
    • Validate page break markers (epub:type="pagebreak"), insert missing ones if page list exists
    │
    ▼
[Stage 6] CSS Sanitization
    • Strip unused selectors
    • Normalize font sizes to em/rem
    • Strip hardcoded colors that break night mode
    • Ensure viewport compatibility across Kobo, Kindle, PocketBook, Apple Books
    │
    ▼
[Stage 7] Repack & Final Validation
    • Rebuild ZIP with correct mimetype ordering
    • Re-run built-in validator; compare error/warning counts before vs. after
    • Emit structured repair-report.json (fixes applied, confidence scores, manual review flags)
    │
    ▼
Output EPUB  +  repair-report.json
```

---

## Confidence Scores & Human-in-the-Loop

Every change Colophon makes carries a confidence level:

- **High confidence** (auto-apply by default): ligature normalization, hard carriage return removal, clear OCR noise, container violations detected by the built-in validator
- **Medium confidence** (apply but flag in report): proper noun canonicalization, chapter boundary splits, header/footer removal
- **Low confidence** (flag for manual review, do not auto-apply): dinkus insertion, missing italics candidates, ambiguous name variants

The repair report is human-readable and actionable. A `--interactive` mode (v0.2) will pause at low-confidence decisions and prompt for user confirmation. A `--dry-run` flag previews all changes without applying them.

Optionally, users can provide **hints via config** — e.g., `"character_names": ["T'Pring", "McCoy", "Spock"]` — to seed the graph with ground truth before analysis.

---

## LLM / AI Backend

Colophon uses **LiteLLM** as the AI abstraction layer, giving users a single config entry to swap between:

- Local models via Ollama (`mistral`, `llama3`, `phi3`, etc.) — default, no API key required
- OpenAI (`gpt-5.5`, `gpt-5.4-mini`)
- Anthropic (`claude-haiku-4-5`, `claude-sonnet-4-6`)
- Any other LiteLLM-supported provider

The LLM is **enhancing** decisions made by deterministic stages, not replacing them. If no LLM is configured, Colophon falls back to spaCy + regex for NER and chapter detection. The LLM accelerates and improves confidence; it is never a hard dependency for core repair.

---

## Semantic Graph Persistence

By default, `book_graph.json` is written as a sibling file to the source EPUB (`book.colophon.json`) rather than discarded after the pipeline run. This is optional and controlled by config (`persist_graph: true/false`, default `true`).

**Why persist:**
- Subsequent runs skip Stage 1 re-analysis if the EPUB is unchanged (validated via SHA-256 checksum stored in the graph file header)
- The EPUB MCP server can load the graph directly without re-parsing the book
- User hint overrides (e.g., `character_names` config) and manual corrections accumulate across runs rather than being re-inferred each time

**Storage paths (in priority order):**
1. Calibre book data folder (`book_data/colophon/book_graph.json`) — set automatically by the Calibre plugin
2. Sibling to the EPUB (`/path/to/book.colophon.json`) — CLI and library API default
3. Explicit path via `--graph-path` CLI flag or `graph_output_path` config key

**Cache invalidation:** The graph header stores the source EPUB's SHA-256. On subsequent runs, if the checksum matches, Stage 1 is skipped. If it doesn't match (EPUB was edited), the graph is regenerated and the old file is overwritten. A `--rebuild-graph` flag forces regeneration regardless.

---

## Format Support

| Format | Status |
|---|---|
| EPUB 3 | Primary target |
| EPUB 2 | Full support; optional upgrade path to EPUB 3 |
| Other formats (MOBI, AZW3, FB2, etc.) | Out of scope — use Calibre or other converter tool to convert first, then repair with Colophon |

---

## Delivery Targets

| Target | Priority | Notes |
|---|---|---|
| CLI (`pip install colophon`) | v0.1 | Primary interface |
| Python library API | v0.1 | Falls out of modular design naturally |
| Calibre plugin | v0.3 | High priority — target MobileRead forum community |
| MCP server (EPUB understanding) | Future | See below |

---

## Module Layout

```
colophon/
├── cli.py                  # Click-based CLI entry point
├── pipeline.py             # Stage orchestration
├── stages/
│   ├── unpack.py           # Stage 0
│   ├── analysis.py         # Stage 1 — builds the semantic book graph (the AI spine; not yet implemented)
│   ├── html_repair.py      # Stage 2
│   ├── text_cleanup.py     # Stage 3
│   ├── chapter_detect.py   # Stage 4
│   ├── toc_rebuild.py      # Stage 5
│   ├── css_sanitize.py     # Stage 6
│   └── repack.py           # Stage 7
├── models/                 # Optional AI model adapters
│   ├── spacy_detector.py
│   └── llm_adapter.py
├── validator.py            # Pure-Python EPUB validator (no Java/epubcheck required)
├── report.py               # Structured repair report output
├── config.py               # Pipeline configuration schema
└── tests/
    └── fixtures/           # Broken EPUB test cases
```

---

## User Stories

- **As an editor**, I run `colophon fix book.epub` and get back a clean, validated EPUB without opening Sigil
- **As a developer**, I add a custom stage by dropping a module into `stages/` and registering it in config — no core changes needed
- **As a reader with a collection**, I run `colophon fix ./my-library --batch` against a folder and get a report of what was fixed vs. what needs manual review
- **As a contributor**, I pick up a clearly scoped stage, write tests against the fixture EPUBs, and submit a PR that touches nothing outside its module

---

## Roadmap

| Milestone | Scope |
|---|---|
| **v0.1 — Core Pipeline** | Unpack/validate (built-in pure-Python validator), basic HTML repair, TOC rebuild, repack, CLI skeleton, repair report |
| **v0.2 — Text Cleanup** | Ligature fix, hard hyphen/CR removal, OCR noise, `--interactive` mode, confidence scores |
| **v0.3 — Semantic Graph + Proper Nouns** | NER, variant clustering, proper noun consistency, Calibre plugin alpha |
| **v0.4 — Chapter Detection & Page Numbers** | Heading/topic-shift splitting, dinkus recovery, page-list nav, header/footer artifact removal |
| **v0.5 — CSS + EPUB 2→3 Upgrade** | CSS sanitization, optional EPUB version upgrade path |
| **v1.0 — Stable** | Full test coverage, contributor docs, PyPI release, Calibre plugin stable |
| **Future — OCR Source Scanning** | Tesseract integration for non-text PDFs and Amazon Topaz `.tpz` files; ground-truth scan validation (provide a physical scan as reference to validate AI inferences) |
| **Future — EPUB MCP Server** | An MCP server exposing book structure (chapters, entities, TOC) as navigable resources, enabling LLMs to reliably answer "summarize chapter 12" without hallucinating scope or getting confused about a structure they don't know how to effectively parse |

---

## A Note on the EPUB MCP / LLM Understanding Angle

Current LLMs understand EPUB as "a ZIP file with HTML inside" but not as a *book* — they lose chapter boundaries, conflate sections, and read/ingest/summarize the wrong scope. The EPUB MCP server addresses this as a companion project:

- Parse EPUB structure using Colophon's analysis stage
- Expose chapters as discrete MCP resources
- Let an LLM call `get_chapter(12)` and get exactly that chapter's text
- The MCP can build and then allow queries of the knowledge graph
- Enable reliable chapter-scoped summarization, Q&A, and annotation

This doesn't require fine-tuning or LoRA. It's a **retrieval problem disguised as an understanding problem** — the LLM is fine at summarizing text; it just needs to be handed the right text that's structured in a way LLMs already natively understand. Colophon's semantic graph is the index that makes that possible. An EPUB→clean-HTML pipeline is the right implementation: structured, well-labeled HTML that LLMs handle better than raw EPUB XML.

---

## Existing Tools Landscape

- **EpubDoctor**: Strong on structural repair, weak on text cleanup
- **epub-utils**: Excellent for inspection, not repair
- **epubrepairtool**: Good for semantic HTML normalization, lacks OCR/AI features
- **Sigil**: Excellent manual editor, no automation
- **Calibre**: Broad format support, good conversion, limited repair automation
- **Pandoc**: Format conversion, not repair

---

## Model Tournament QA

To validate LLM quality across providers and hardware tiers, the test suite includes a tournament harness. The goal: run the same repair task against multiple models and score the output objectively, so we know which model is best for which task before committing it as the default.

### Tournament design

Each tournament run:
1. Takes a fixture EPUB with known defects
2. Runs Stage 1 (analysis / book graph extraction) with each candidate model
3. Scores each model's `book_graph.json` output against a hand-labeled ground truth JSON
4. Optionally runs a full pipeline pass and scores the repaired EPUB on the same rubric
5. Emits a `tournament_results.json` with per-model scores, latency, and token cost

### Scoring rubric (Stage 1)

| Metric | Weight | How measured |
|---|---|---|
| Character recall | 30% | % of ground-truth characters found |
| Character precision | 20% | % of extracted characters that are real (no hallucinations) |
| Variant cluster accuracy | 20% | % of known variant groups correctly merged |
| Chapter boundary F1 | 20% | Precision × recall on known chapter split points |
| JSON schema compliance | 10% | Does the output parse and validate against the schema? |

### Candidate models (initial tournament set)

| Model | Provider | Context | Notes |
|---|---|---|---|
| `gemma4:26b-mlx-bf16` | Ollama / Mac Studio (Tailnet) | 262K | Primary local candidate; 256 GB unified memory |
| `gemma3:12b` | Ollama local | 128K | Lower-resource local fallback |
| `claude-haiku-4-5` | Anthropic API | 200K | Cloud default; cheap per token |
| `claude-sonnet-4-6` | Anthropic API | 200K | Cloud quality tier |

### CLI usage

```bash
# Run tournament on a single fixture against all configured models
colophon tournament tests/fixtures/the-lost-years.epub

# Run tournament on all fixtures, write results to a directory
colophon tournament tests/fixtures/ --batch --results-dir tournament_results/

# Add a model to the tournament roster (stored in config)
colophon tournament --add-model ollama/gemma4:26b-mlx-bf16 \
    --ollama-url http://100.122.243.79:11434 --num-ctx 262144
```

### Test suite integration

`tests/test_tournament.py` will:
- Skip automatically if `COLOPHON_TOURNAMENT=1` is not set (prevents slow LLM calls in normal CI)
- Load ground-truth labels from `tests/fixtures/ground_truth/<fixture_stem>.json`
- Assert that the default model scores ≥ 0.70 on character recall (regression gate)
- Emit a Markdown summary table for human review

Ground truth files are committed to the repo (they are hand-labeled metadata, not copyrighted content).

---

## Open Questions

- Calibre plugin architecture: full plugin vs. subprocess wrapper for v0.3?
- Ground-truth scan validation: what format/resolution is minimally useful?
- `--interactive` UI: terminal prompts (simple) vs. lightweight web UI (richer but heavier)?
- Dinkus recovery: threshold for "confident enough to auto-insert" vs. "flag only"?
- How do handle dependencies for other tools we'll be using so as not to reinvent the wheel