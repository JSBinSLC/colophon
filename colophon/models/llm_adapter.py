"""LiteLLM wrapper — single call site for all LLM interactions in Colophon.

Supports any provider LiteLLM understands:
  - anthropic/claude-haiku-4-5       (default; cloud)
  - anthropic/claude-sonnet-4-6      (larger context headroom)
  - ollama/gemma3:12b                 (local; no key required)
  - ollama/mistral                    (local fallback)

The caller passes a PipelineConfig and the adapter resolves credentials
from config.llm.resolved_api_key(), which checks the explicit field first
and falls back to ANTHROPIC_API_KEY from the environment (loaded from .env
by cli.py at startup).
"""
from __future__ import annotations

import json
from typing import Any

import litellm

from colophon.config import LLMConfig


class LLMAdapter:
    def __init__(self, cfg: LLMConfig) -> None:
        self._cfg = cfg
        # Suppress litellm's verbose success/failure logging.
        litellm.set_verbose = False  # type: ignore[attr-defined]

    def complete(self, system: str, user: str) -> str:
        """Send a single system+user turn; return the assistant text."""
        api_key = self._cfg.resolved_api_key()
        kwargs: dict[str, Any] = {
            "model": self._cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "timeout": self._cfg.timeout,
        }
        if api_key:
            kwargs["api_key"] = api_key

        response = litellm.completion(**kwargs)
        return response.choices[0].message.content or ""

    def complete_json(self, system: str, user: str) -> Any:
        """Like complete(), but parse and return the JSON from the response.

        Raises ValueError if the model returns non-JSON text.
        """
        raw = self.complete(system, user)
        # Strip markdown code fences if the model wrapped the JSON.
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            # Drop first line (```json or ```) and last line (```)
            text = "\n".join(lines[1:-1]).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"LLM returned non-JSON response: {raw[:200]!r}"
            ) from exc
