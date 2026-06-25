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
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from lxml import etree

from colophon.config import PipelineConfig
from colophon.models.llm_adapter import LLMAdapter
from colophon.models.model_info import ModelInfo, probe_model
from colophon.stages import Stage

log = logging.getLogger(__name__)

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

        # Cache hit: skip LLM only if the stored graph was built from the same
        # source bytes, by the same model, under the same schema. Switching
        # models (or bumping the schema) must force a rebuild — otherwise a
        # model-comparison run silently reuses the previous model's graph.
        if not config.rebuild_graph and graph_path.exists():
            existing = json.loads(graph_path.read_text(encoding="utf-8"))
            if (
                existing.get("source_sha256") == source_sha256
                and existing.get("model") == config.llm.model
                and existing.get("schema_version") == GRAPH_SCHEMA_VERSION
            ):
                ctx["book_graph"] = existing
                ctx["graph_path"] = graph_path
                return

        spine_texts = _extract_spine_texts(work_dir)
        if not spine_texts:
            ctx["book_graph"] = empty_graph(source_sha256, config.llm.model)
            ctx["graph_path"] = graph_path
            return

        # Probe the model before sending anything: pick up the real max output
        # tokens (LiteLLM doesn't know them for OpenRouter models) and let
        # _build_graph preview chunk count and cost.
        info = probe_model(config.llm.model, config.llm.resolved_api_key())
        if info.max_output_tokens and not config.llm.max_output_tokens:
            config.llm.max_output_tokens = info.max_output_tokens

        adapter = LLMAdapter(config.llm)
        graph = _build_graph(adapter, config, spine_texts, source_sha256, info)

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
    adapter: LLMAdapter,
    label: str,
    user_msg: str,
    max_retries: int = 5,
) -> dict | None:
    """Call adapter.complete_json with exponential backoff on transient errors.

    Retries rate limits and transient server/network failures (5xx, connection
    drops, timeouts) — anything that would otherwise silently drop an entire
    chunk's entities. Non-JSON responses and other errors are not retried.
    """
    import litellm

    retryable = (
        litellm.RateLimitError,
        litellm.InternalServerError,
        litellm.ServiceUnavailableError,
        litellm.APIConnectionError,
        litellm.Timeout,
    )

    delay = 15.0
    for attempt in range(max_retries):
        try:
            return adapter.complete_json(_SYSTEM_PROMPT, user_msg)
        except retryable as exc:
            if attempt == max_retries - 1:
                log.warning("Stage 1: %s exhausted retries after %s, giving up",
                            label, type(exc).__name__)
                return None
            log.warning("Stage 1: %s transient error (%s), retrying in %.0fs (attempt %d/%d)",
                        label, type(exc).__name__, delay, attempt + 1, max_retries)
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
    info: ModelInfo | None = None,
) -> dict[str, Any]:
    """Run LLM analysis over all spine items (chunked if needed) and merge."""
    if config.llm.max_chunk_chars:
        usable_chars = config.llm.max_chunk_chars
    elif config.llm.num_ctx:
        context_chars = (config.llm.num_ctx - PROMPT_OVERHEAD_TOKENS) * CHARS_PER_TOKEN
        usable_chars = max(1, min(context_chars, MAX_CHUNK_CHARS))
    else:
        usable_chars = MAX_CHUNK_CHARS

    chunks = _chunk_spine(spine_texts, usable_chars)
    _log_run_preview(config.llm.model, chunks, info)

    if config.llm.use_batch and config.llm.model.startswith("openai/"):
        partial_graphs = _build_graph_batch(config, chunks)
        if partial_graphs is None:
            log.warning("Stage 1: batch unavailable, falling back to direct calls")
            partial_graphs = _analyze_chunks(adapter, chunks, config.llm.max_concurrency)
    else:
        partial_graphs = _analyze_chunks(adapter, chunks, config.llm.max_concurrency)

    graph = empty_graph(source_sha256, config.llm.model)
    if partial_graphs:
        _merge_into(graph, partial_graphs)
    return graph


def _log_run_preview(
    model: str, chunks: list[dict[str, Any]], info: ModelInfo | None
) -> None:
    """Log chunk count, input size, and an estimated cost before the run."""
    total_chars = sum(len(c["text"]) for c in chunks)
    in_tokens = total_chars // CHARS_PER_TOKEN
    msg = f"Stage 1: {len(chunks)} chunk(s), ~{in_tokens:,} input tokens, model {model}"
    if info and info.max_output_tokens:
        msg += f" (max output {info.max_output_tokens:,}/chunk)"
    if info and info.input_cost_per_token:
        # Output size is unknown ahead of time; estimate it at ~20% of input
        # (a rough ratio for entity extraction) for an order-of-magnitude figure.
        in_cost = in_tokens * info.input_cost_per_token
        out_cost = in_tokens * 0.2 * (info.output_cost_per_token or 0.0)
        msg += f"; est. ~${in_cost + out_cost:.3f}"
    log.info(msg)


def _analyze_chunks(
    adapter: LLMAdapter, chunks: list[dict[str, Any]], max_concurrency: int
) -> list[dict[str, Any]]:
    """Analyze every chunk, optionally in parallel, preserving chunk order.

    Order matters: _merge_into derives chapter ordering from the sequence of
    partial responses, so results are reassembled by chunk index regardless of
    completion order. Failed chunks (returned None by the backoff helper) are
    dropped.
    """
    workers = max(1, min(max_concurrency, len(chunks)))
    if workers == 1:
        return _sequential_analyze(adapter, chunks)

    log.info("Stage 1: analyzing %d chunks with concurrency=%d", len(chunks), workers)

    def _work(i: int, chunk: dict[str, Any]) -> dict[str, Any] | None:
        label = f"chunk {i + 1}/{len(chunks)}"
        user_msg = f"Book passage ({label}):\n\n{chunk['text']}"
        return _call_with_backoff(adapter, label, user_msg)

    results: list[dict[str, Any] | None] = [None] * len(chunks)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_work, i, c): i for i, c in enumerate(chunks)}
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()

    return [r for r in results if r is not None]


def _sequential_analyze(
    adapter: LLMAdapter, chunks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Call the LLM once per chunk, in order, with exponential backoff."""
    partials: list[dict[str, Any]] = []
    for i, chunk in enumerate(chunks):
        label = f"chunk {i + 1}/{len(chunks)}"
        user_msg = f"Book passage ({label}):\n\n{chunk['text']}"
        result = _call_with_backoff(adapter, label, user_msg)
        if result is not None:
            partials.append(result)
    return partials


def _build_graph_batch(
    config: PipelineConfig,
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    """Submit all chunks to the OpenAI Batch API; poll until complete.

    Returns the list of partial graph dicts on success, or None if the openai
    package is unavailable (signals the caller to fall back to sequential).

    Pricing: ~50% cheaper than real-time; completion window up to 24h.
    Only called when config.llm.use_batch is True and model is openai/*.
    """
    import io

    try:
        import openai as _openai
    except ImportError:  # pragma: no cover
        log.warning("Stage 1 batch: openai package not installed")
        return None

    api_key  = config.llm.resolved_api_key()
    model_id = config.llm.model.split("/", 1)[-1]  # "openai/gpt-5.4-mini" → "gpt-5.4-mini"

    client = _openai.OpenAI(api_key=api_key)

    # Build one JSONL request per chunk
    requests = [
        {
            "custom_id": f"chunk-{i}",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": f"Book passage (chunk {i + 1}/{len(chunks)}):\n\n{chunk['text']}"},
                ],
                "temperature": config.llm.temperature,
                "response_format": {"type": "json_object"},
            },
        }
        for i, chunk in enumerate(chunks)
    ]
    jsonl = ("\n".join(json.dumps(r) for r in requests) + "\n").encode("utf-8")

    log.info("Stage 1 batch: uploading %d chunks to OpenAI Files API", len(requests))
    batch_file = client.files.create(
        file=("batch.jsonl", io.BytesIO(jsonl), "application/jsonl"),
        purpose="batch",
    )

    batch = client.batches.create(
        input_file_id=batch_file.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
    )
    log.info(
        "Stage 1 batch: submitted batch_id=%s  chunks=%d  poll_interval=%ds",
        batch.id, len(requests), config.llm.batch_poll_interval,
    )

    _TERMINAL = frozenset({"completed", "failed", "expired", "cancelled"})
    deadline = time.time() + config.llm.batch_timeout

    while batch.status not in _TERMINAL:
        if time.time() > deadline:
            log.error(
                "Stage 1 batch: timed out after %ds waiting for batch %s",
                config.llm.batch_timeout, batch.id,
            )
            return []
        elapsed = int(time.time() - (deadline - config.llm.batch_timeout))
        log.info(
            "Stage 1 batch: status=%s  elapsed=%ds  batch_id=%s",
            batch.status, elapsed, batch.id,
        )
        time.sleep(config.llm.batch_poll_interval)
        batch = client.batches.retrieve(batch.id)

    if batch.status != "completed":
        log.error(
            "Stage 1 batch: batch %s ended with status=%s", batch.id, batch.status,
        )
        return []

    log.info("Stage 1 batch: batch %s completed", batch.id)

    # Download and parse results
    output_text = client.files.content(batch.output_file_id).text
    partials: list[dict[str, Any]] = []
    for line in output_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            raw = entry["response"]["body"]["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            log.warning("Stage 1 batch: malformed result entry, skipping")
            continue

        # Same cleanup as LLMAdapter.complete_json
        text = raw.strip()
        if text.startswith("```"):
            text = "\n".join(text.splitlines()[1:-1]).strip()
        if text.startswith("---"):
            text = text.lstrip("-").strip()

        try:
            partials.append(json.loads(text))
        except json.JSONDecodeError:
            log.warning("Stage 1 batch: non-JSON result: %r", raw[:120])

    log.info(
        "Stage 1 batch: parsed %d/%d results", len(partials), len(requests),
    )
    return partials


def _split_text(text: str, max_chars: int) -> list[str]:
    """Break text into pieces of at most max_chars, preferring paragraph breaks.

    A spine item larger than the chunk size must be *split*, never truncated —
    truncating silently drops most of a book that ships as a few big HTML files.
    Paragraphs (\\n\\n) are kept intact where possible; a single paragraph longer
    than max_chars is hard-split as a last resort.
    """
    if len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    buf: list[str] = []
    buf_len = 0

    def flush() -> None:
        nonlocal buf, buf_len
        if buf:
            pieces.append("\n\n".join(buf))
            buf = []
            buf_len = 0

    for para in text.split("\n\n"):
        # A paragraph that alone exceeds the window: flush, then hard-split it.
        while len(para) > max_chars:
            flush()
            pieces.append(para[:max_chars])
            para = para[max_chars:]
        if buf and buf_len + len(para) + 2 > max_chars:
            flush()
        buf.append(para)
        buf_len += len(para) + 2

    flush()
    return pieces


def _chunk_spine(
    spine_texts: list[dict[str, str]], max_chars: int
) -> list[dict[str, Any]]:
    """Group spine items into chunks that fit within max_chars.

    Oversized spine items are split into multiple pieces (see _split_text) so
    the whole book is analyzed, not just the opening of each large file.
    """
    # Expand each spine item into segments no larger than max_chars.
    segments: list[dict[str, str]] = []
    for item in spine_texts:
        for piece in _split_text(item["text"], max_chars):
            segments.append({"href": item["href"], "text": piece})

    chunks: list[dict[str, Any]] = []
    current_parts: list[dict[str, str]] = []
    current_len = 0

    for seg in segments:
        if current_parts and current_len + len(seg["text"]) > max_chars:
            chunks.append({
                "text": "\n\n---\n\n".join(p["text"] for p in current_parts),
                "hrefs": [p["href"] for p in current_parts],
            })
            current_parts = []
            current_len = 0
        current_parts.append(seg)
        current_len += len(seg["text"])

    if current_parts:
        chunks.append({
            "text": "\n\n---\n\n".join(p["text"] for p in current_parts),
            "hrefs": [p["href"] for p in current_parts],
        })
    return chunks


def _merge_into(graph: dict[str, Any], partials: list[dict[str, Any]]) -> None:
    """Merge partial graph responses into the master graph.

    Entities are clustered across chunks so that different surface forms of
    the same entity (e.g. "Kirk", "Jim Kirk", "James T. Kirk") collapse into a
    single record — the variant-resolution that is the graph's whole point.
    """
    for category in ("characters", "places", "organizations", "invented_terms"):
        entries = _collect_entries(partials, category)
        graph["entities"][category] = _cluster_and_merge(
            entries, person_names=(category == "characters")
        )

    # Chapters: deduplicate by title, preserve order, re-index.
    seen_titles: set[str] = set()
    chapters: list[dict[str, Any]] = []
    for partial in partials:
        for ch in partial.get("chapters", []):
            title = (ch.get("title") or "").strip()
            if title and title not in seen_titles:
                seen_titles.add(title)
                chapters.append(ch)
    for i, ch in enumerate(chapters):
        ch["index"] = i
    graph["chapters"] = chapters


def _coerce_count(value: Any) -> int:
    """Best-effort conversion of an LLM-supplied occurrence count to int."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _collect_entries(partials: list[dict[str, Any]], category: str) -> list[dict[str, Any]]:
    """Flatten one entity category across all partial responses."""
    entries: list[dict[str, Any]] = []
    for partial in partials:
        for entity in partial.get(category, []):
            canonical = (entity.get("canonical") or "").strip()
            if not canonical:
                continue
            variants = {
                v.strip() for v in entity.get("variants", []) if v and v.strip()
            }
            variants.discard(canonical)
            entries.append({
                "canonical": canonical,
                "variants": variants,
                "occurrences": _coerce_count(entity.get("occurrences")),
            })
    return entries


# Honorific titles and ranks stripped when matching personal names, so that
# "Mr. Foster" / "Captain Kirk" reduce to their surname for comparison.
_HONORIFICS = frozenset({
    "mr", "mrs", "ms", "miss", "mx", "dr", "sir", "madam", "madame",
    "monsieur", "mlle", "mme", "lord", "lady", "master", "st", "saint",
    "prof", "professor", "rev", "reverend", "father", "captain", "capt",
    "lieutenant", "lt", "commander", "cmdr", "admiral", "colonel", "col",
    "major", "general", "gen", "sergeant", "sgt", "king", "queen", "prince",
    "princess", "duke", "duchess", "count", "countess", "baron", "baroness",
})


def _name_parts(name: str) -> list[str]:
    """Lowercased name tokens with honorific titles removed.

    "Mr. Foster" -> ["foster"], "Henry Foster" -> ["henry", "foster"],
    "Captain Kirk" -> ["kirk"]. The last token is treated as the surname.
    """
    raw = re.findall(r"[^\W_]+", name.lower())
    return [t for t in raw if t not in _HONORIFICS]


def _cluster_and_merge(
    entries: list[dict[str, Any]], person_names: bool = False
) -> list[dict[str, Any]]:
    """Group entries that refer to the same entity and merge each group.

    Two entries are linked when one's canonical form appears as a surface form
    (canonical or variant) of the other. Linking only on *canonical* matches —
    never variant-to-variant — avoids generic titles like "Admiral" wrongly
    bridging two distinct characters.

    When ``person_names`` is set (the characters category), a second pass attaches
    a short form (a lone surname, with or without a title — "Foster", "Mr.
    Foster") to a full name that shares that surname ("Henry Foster") — but only
    when exactly ONE person in the graph has that surname. If two people share it
    (e.g. "James Kirk" and "George Kirk"), the short form is ambiguous and left
    alone for the LLM reconciliation pass.
    """
    n = len(entries)
    if n == 0:
        return []

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    canons = [e["canonical"].lower() for e in entries]
    surfaces = [
        {e["canonical"].lower()} | {v.lower() for v in e["variants"]}
        for e in entries
    ]
    for i in range(n):
        for j in range(i + 1, n):
            if canons[i] in surfaces[j] or canons[j] in surfaces[i]:
                union(i, j)

    # Personal-name pass: attach lone-surname forms ("Mr. Foster", "Foster") to
    # the full name that shares the surname — only when that surname is unique.
    if person_names:
        parts = [_name_parts(e["canonical"]) for e in entries]
        # Distinct people (post step-1 clusters) that carry each surname as part
        # of a *full* name (>= 2 tokens after honorific stripping).
        surname_people: dict[str, set[int]] = defaultdict(set)
        for i in range(n):
            if len(parts[i]) >= 2:
                surname_people[parts[i][-1]].add(find(i))
        for i in range(n):
            # A short form is a single token (the surname), e.g. "Foster" or,
            # after stripping the title, "Mr. Foster".
            if len(parts[i]) != 1:
                continue
            people = {r for r in surname_people.get(parts[i][0], set()) if r != find(i)}
            if len(people) == 1:
                union(i, next(iter(people)))

    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(entries[i])

    merged: list[dict[str, Any]] = []
    for group in groups.values():
        # Canonical = the surface form with the most occurrences; ties broken
        # toward the longer (more complete) and then lexically larger form.
        totals: dict[str, int] = defaultdict(int)
        for e in group:
            totals[e["canonical"]] += e["occurrences"]
        canonical = max(totals, key=lambda k: (totals[k], len(k), k))

        all_surface: set[str] = set()
        occurrences = 0
        for e in group:
            all_surface.add(e["canonical"])
            all_surface.update(e["variants"])
            occurrences += e["occurrences"]
        all_surface.discard(canonical)

        merged.append({
            "canonical": canonical,
            "variants": sorted(all_surface),
            "occurrences": occurrences,
        })

    return sorted(merged, key=lambda e: -e["occurrences"])
