from __future__ import annotations

import os
from pathlib import Path
from pydantic import BaseModel, Field


_PROVIDER_ENV_KEY: dict[str, str] = {
    "anthropic/":   "ANTHROPIC_API_KEY",
    "openai/":      "OPENAI_API_KEY",
    "openrouter/":  "OPENROUTER_API_KEY",
}


class LLMConfig(BaseModel):
    model: str = "anthropic/claude-haiku-4-5"
    api_key: str | None = None      # None = read from provider env var
    api_base: str | None = None     # Custom endpoint, e.g. http://100.x.x.x:11434
    num_ctx: int | None = None      # Ollama context window override (tokens)
    timeout: int = 600
    # Extraction is a deterministic task — default to greedy decoding so the
    # graph is reproducible run-to-run and the cache stays meaningful.
    temperature: float = 0.0
    # Explicit output-token ceiling. None = resolve the model's documented max
    # at call time (falls back to the provider default if unknown).
    max_output_tokens: int | None = None
    # Number of chunks to analyze concurrently in Stage 1. Cloud providers
    # handle parallel requests well; lower to 1 for a local Ollama server or to
    # stay under a tight rate limit.
    max_concurrency: int = 4
    # Stage 1 LLM reconciliation pass: a final coreference call that groups
    # no-shared-substring aliases the deterministic clustering can't (Pierre =
    # Pyotr Kirillovich = Bezukhov). One extra LLM call; high-confidence only.
    reconcile: bool = True
    # Override the default 32K-char chunk cap. Set large (e.g. 4_000_000) to
    # send the whole book in one shot on 1M-context models like Gemini Flash.
    max_chunk_chars: int | None = None
    # OpenAI Batch API — 50% cheaper, async (up to 24h turnaround).
    # Only active for openai/* models; ignored by other providers.
    use_batch: bool = False
    batch_poll_interval: int = 30   # Seconds between status checks
    batch_timeout: int = 86400      # Give up after this many seconds (default 24h)

    def resolved_api_key(self) -> str | None:
        """Return the API key for the configured provider.

        Explicit api_key wins. Otherwise looks up the provider-specific env var
        (ANTHROPIC_API_KEY for anthropic/ models, OPENAI_API_KEY for openai/
        models). Ollama models need no key — returns None.
        """
        if self.api_key:
            return self.api_key
        for prefix, env_var in _PROVIDER_ENV_KEY.items():
            if self.model.startswith(prefix):
                return os.environ.get(env_var)
        return None


class HintsConfig(BaseModel):
    character_names: list[str] = Field(default_factory=list)
    place_names: list[str] = Field(default_factory=list)


class OutputConfig(BaseModel):
    persist_graph: bool = True
    graph_output_path: Path | None = None  # None = sibling to EPUB


class PipelineConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    hints: HintsConfig = Field(default_factory=HintsConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    dry_run: bool = False
    interactive: bool = False
    rebuild_graph: bool = False

    @classmethod
    def default(cls) -> "PipelineConfig":
        return cls()
