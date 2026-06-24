"""LiteLLM wrapper — single call site for all LLM interactions in Colophon.

Supports any provider LiteLLM understands:
  - anthropic/claude-haiku-4-5       (default; cloud, 200K context, ~$0.15/novel)
  - anthropic/claude-sonnet-4-6      (cloud, larger context headroom)
  - openai/gpt-5.4-mini              (cloud; cheaper than Haiku; set OPENAI_API_KEY)
  - openai/gpt-5.4-nano              (cloud; cheapest extraction baseline)
  - ollama/gemma4:26b-mlx-bf16       (local/Tailnet Ollama, set api_base + num_ctx)
  - ollama/gemma3:12b                 (local Ollama, no key required)

Custom Ollama endpoints (e.g. a Mac Studio on your Tailnet):
  Set api_base="http://100.x.x.x:11434" and num_ctx=262144 in LLMConfig.
"""
from __future__ import annotations

import json
from typing import Any

import litellm

from colophon.config import LLMConfig


class LLMAdapter:
    def __init__(self, cfg: LLMConfig) -> None:
        self._cfg = cfg
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
        if self._cfg.api_base:
            kwargs["api_base"] = self._cfg.api_base
        # Ollama-specific: override the model's built-in context window.
        # LiteLLM forwards num_ctx into the options dict for Ollama requests.
        if self._cfg.num_ctx is not None:
            kwargs["num_ctx"] = self._cfg.num_ctx

        response = litellm.completion(**kwargs)
        return response.choices[0].message.content or ""

    def complete_json(self, system: str, user: str) -> Any:
        """Like complete(), but parse and return the JSON from the response.

        Raises ValueError if the model returns non-JSON text.
        """
        raw = self.complete(system, user)
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]).strip()
        # Some models prefix JSON with a markdown horizontal rule (---).
        if text.startswith("---"):
            text = text.lstrip("-").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"LLM returned non-JSON response: {raw[:200]!r}"
            ) from exc
