from pathlib import Path
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    model: str = "ollama/mistral"
    timeout: int = 60


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
