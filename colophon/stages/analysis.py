"""Stage 1 — Build Semantic Book Graph.

Extracts text from all spine HTML documents, sends it to the configured LLM
in chunks that fit the context window, and assembles a book_graph.json with:

  - Named entities: characters, places, organizations, invented terms
  - Variant spelling clusters (e.g. ["T'Pring", "TPring", "T-Pring"])
  - Chapter boundary candidates inferred from the text
  - Source EPUB SHA-256 for cache invalidation

The graph is written to a .colophon.json file alongside the source EPUB
(or to config.output.graph_output_path if set). Subsequent runs skip Stage 1
when the EPUB checksum matches the stored value, unless --rebuild-graph is set.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

from bs4 import BeautifulSoup
from lxml import etree

from colophon.config import PipelineConfig
from colophon.models.llm_adapter import LLMAdapter
from colophon.stages import Stage

GRAPH_SCHEMA_VERSION = "1"

# Approximate characters per token (conservative for prose).
CHARS_PER_TOKEN = 4
# Reserve tokens for system prompt + JSON response output.
PROMPT_OVERHEAD_TOKENS = 4000
# Hard cap per chunk: ~8K tokens of input regardless of context window size.
# Keeps JSON output from being truncated on large-context models.
MAX_CHUNK_CHARS = 32_000


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def empty_graph(source_sha256: str, model: str) -> dict[str, Any]:
    return {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "source_sha256": source_sha256,
        "model": model,
        "entities": {
            "characters": [],
            "places": [],
            "organizations": [],
            "invented_terms": [],
        },
        "chapters": [],
    }


# ---------------------------------------------------------------------------
# Stage
# ---------------------------------------------------------------------------

class AnalysisStage(Stage):
    label = "Stage 1 — Semantic graph analysis"

    def run(self, ctx: dict) -> None:
        epub_path: Path = ctx["epub_path"]
        config: PipelineConfig = ctx["config"]
        work_dir: Path = ctx["work_dir"]

        graph_path = _resolve_graph_path(epub_path, config)
        source_sha256 = _sha256(epub_path)

        # Cache hit: skip LLM if graph is current and --rebuild-graph not set.
        if not config.rebuild_graph and graph_path.exists():
            existing = json.loads(graph_path.read_text(encoding="utf-8"))
            if existing.get("source_sha256") == source_sha256:
                ctx["book_graph"] = existing
                ctx["graph_path"] = graph_path
                return

        spine_texts = _extract_spine_texts(work_dir)
        if not spine_texts:
            ctx["book_graph"] = empty_graph(source_sha256, config.llm.model)
            ctx["graph_path"] = graph_path
            return

        adapter = LLMAdapter(config.llm)
        graph = _build_graph(adapter, config, spine_texts, source_sha256)

        if config.output.persist_graph:
            graph_path.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")

        ctx["book_graph"] = graph
        ctx["graph_path"] = graph_path

    def analyze(self, ctx: dict) -> None:
        """Dry-run: just report what the graph path would be."""
        epub_path: Path = ctx["epub_path"]
        config: PipelineConfig = ctx["config"]
        graph_path = _resolve_graph_path(epub_path, config)
        ctx["graph_path"] = graph_path


# ---------------------------------------------------------------------------
# Graph path resolution
# ---------------------------------------------------------------------------

def _resolve_graph_path(epub_path: Path, config: PipelineConfig) -> Path:
    if config.output.graph_output_path:
        return config.output.graph_output_path
    return epub_path.with_suffix(".colophon.json")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def _extract_spine_texts(work_dir: Path) -> list[dict[str, str]]:
    """Return spine items in order as [{"href": ..., "text": ...}]."""
    container = work_dir / "META-INF" / "container.xml"
    if not container.exists():
        return []

    root = etree.parse(str(container)).getroot()
    ns = {"cnt": "urn:oasis:names:tc:opendocument:xmlns:container"}
    rootfiles = root.findall(".//cnt:rootfile", ns)
    if not rootfiles:
        return []

    opf_path = work_dir / rootfiles[0].get("full-path", "")
    if not opf_path.exists():
        return []

    opf_root = etree.parse(str(opf_path)).getroot()
    opf_ns = {"opf": "http://www.idpf.org/2007/opf"}
    opf_dir = opf_path.parent

    # Build id → href manifest map.
    manifest: dict[str, Path] = {}
    for item in opf_root.findall(".//opf:item", opf_ns):
        item_id = item.get("id", "")
        href = item.get("href", "")
        media_type = item.get("media-type", "")
        if media_type in ("application/xhtml+xml", "text/html"):
            manifest[item_id] = opf_dir / href

    # Follow spine order.
    spine_items = []
    for itemref in opf_root.findall(".//opf:itemref", opf_ns):
        idref = itemref.get("idref", "")
        path = manifest.get(idref)
        if path and path.exists():
            text = _html_to_text(path)
            if text.strip():
                spine_items.append({"href": path.name, "text": text})

    return spine_items


def _html_to_text(html_path: Path) -> str:
    """Strip HTML tags; return clean prose text."""
    html = html_path.read_bytes()
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    # Collapse runs of blank lines to at most two.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# LLM analysis
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a literary analyst. Given a passage from a book, extract structured information and return it as valid JSON with no other text.

Return exactly this structure:
{
  "characters": [
    {"canonical": "string", "variants": ["string"], "occurrences": number}
  ],
  "places": [
    {"canonical": "string", "variants": ["string"], "occurrences": number}
  ],
  "organizations": [
    {"canonical": "string", "variants": ["string"], "occurrences": number}
  ],
  "invented_terms": [
    {"canonical": "string", "variants": ["string"], "occurrences": number}
  ],
  "chapters": [
    {"index": number, "title": "string", "spine_item": "string", "first_line": "string"}
  ]
}

Rules:
- canonical: the most frequently used / most complete spelling
- variants: ALL other observed spellings of the same entity (may be empty list)
- occurrences: approximate count across the passage
- invented_terms: bespoke proper nouns that are not characters, places, or orgs (ships, spells, alien species, made-up words)
- chapters: infer chapter breaks from headings like "Chapter 1", "PART TWO", roman numerals, or ALL-CAPS titles
- Do not include common English words or generic nouns
- Return only the JSON object, no markdown, no explanation
"""


def _call_with_backoff(
    adapter: "LLMAdapter",
    label: str,
    user_msg: str,
    max_retries: int = 5,
) -> "dict | None":
    """Call adapter.complete_json with exponential backoff on rate-limit errors."""
    import litellm

    delay = 15.0
    for attempt in range(max_retries):
        try:
            return adapter.complete_json(_SYSTEM_PROMPT, user_msg)
        except litellm.RateLimitError:
            if attempt == max_retries - 1:
                log.warning("Stage 1: %s hit rate limit, giving up after %d retries", label, max_retries)
                return None
            log.warning("Stage 1: %s rate-limited, retrying in %.0fs (attempt %d/%d)",
                        label, delay, attempt + 1, max_retries)
            time.sleep(delay)
            delay = min(delay * 2, 120)
        except ValueError as exc:
            log.warning("Stage 1: %s returned non-JSON: %s", label, exc)
            return None
        except Exception as exc:
            log.warning("Stage 1: %s failed (%s): %s", label, type(exc).__name__, exc)
            return None
    return None


def _build_graph(
    adapter: LLMAdapter,
    config: PipelineConfig,
    spine_texts: list[dict[str, str]],
    source_sha256: str,
) -> dict[str, Any]:
    """Run LLM analysis over all spine items (chunked if needed) and merge."""
    max_tokens = config.llm.num_ctx or 8192
    context_chars = (max_tokens - PROMPT_OVERHEAD_TOKENS) * CHARS_PER_TOKEN
    usable_chars = min(context_chars, MAX_CHUNK_CHARS)

    chunks = _chunk_spine(spine_texts, usable_chars)
    partial_graphs: list[dict[str, Any]] = []

    for i, chunk in enumerate(chunks):
        label = f"chunk {i + 1}/{len(chunks)}"
        user_msg = f"Book passage ({label}):\n\n{chunk['text']}"
        result = _call_with_backoff(adapter, label, user_msg)
        if result is not None:
            partial_graphs.append(result)

    graph = empty_graph(source_sha256, config.llm.model)
    if partial_graphs:
        _merge_into(graph, partial_graphs, spine_texts)

    return graph


def _chunk_spine(
    spine_texts: list[dict[str, str]], max_chars: int
) -> list[dict[str, Any]]:
    """Group spine items into chunks that fit within max_chars."""
    chunks: list[dict[str, Any]] = []
    current_parts: list[dict[str, str]] = []
    current_len = 0

    for item in spine_texts:
        text_len = len(item["text"])
        if current_parts and current_len + text_len > max_chars:
            chunks.append({
                "text": "\n\n---\n\n".join(p["text"] for p in current_parts),
                "hrefs": [p["href"] for p in current_parts],
            })
            current_parts = []
            current_len = 0
        # If a single item exceeds the window, truncate it.
        text = item["text"]
        if text_len > max_chars:
            text = text[:max_chars]
        current_parts.append({"href": item["href"], "text": text})
        current_len += len(text)

    if current_parts:
        chunks.append({
            "text": "\n\n---\n\n".join(p["text"] for p in current_parts),
            "hrefs": [p["href"] for p in current_parts],
        })
    return chunks


def _merge_into(
    graph: dict[str, Any],
    partials: list[dict[str, Any]],
    spine_texts: list[dict[str, str]],
) -> None:
    """Merge partial graph responses into the master graph."""
    for category in ("characters", "places", "organizations", "invented_terms"):
        seen: dict[str, dict[str, Any]] = {}
        for partial in partials:
            for entity in partial.get(category, []):
                canonical = entity.get("canonical", "").strip()
                if not canonical:
                    continue
                key = canonical.lower()
                if key in seen:
                    # Merge variants and sum occurrences.
                    existing = seen[key]
                    new_variants = set(existing.get("variants", []))
                    new_variants.update(entity.get("variants", []))
                    new_variants.discard(canonical)
                    existing["variants"] = sorted(new_variants)
                    existing["occurrences"] = (
                        existing.get("occurrences", 0) + entity.get("occurrences", 0)
                    )
                else:
                    seen[key] = {
                        "canonical": canonical,
                        "variants": sorted(set(entity.get("variants", []))),
                        "occurrences": entity.get("occurrences", 0),
                    }
        graph["entities"][category] = sorted(
            seen.values(), key=lambda e: -e["occurrences"]
        )

    # Chapters: deduplicate by title, preserve order.
    seen_titles: set[str] = set()
    chapters: list[dict[str, Any]] = []
    for partial in partials:
        for ch in partial.get("chapters", []):
            title = ch.get("title", "").strip()
            if title and title not in seen_titles:
                seen_titles.add(title)
                chapters.append(ch)
    # Re-index.
    for i, ch in enumerate(chapters):
        ch["index"] = i
    graph["chapters"] = chapters
