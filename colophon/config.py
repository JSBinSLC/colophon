from __future__ import annotations

import os
from pathlib import Path
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    model: str = "anthropic/claude-haiku-4-5"
    api_key: str | None = None      # None = read from ANTHROPIC_API_KEY env var
    api_base: str | None = None     # Custom endpoint, e.g. http://100.x.x.x:11434
    num_ctx: int | None = None      # Ollama context window override (tokens)
    timeout: int = 120

    def resolved_api_key(self) -> str | None:
        """Return the API key, preferring the explicit value over the env var."""
        return self.api_key or os.environ.get("ANTHROPIC_API_KEY")


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
