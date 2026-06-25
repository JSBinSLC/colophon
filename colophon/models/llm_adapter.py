"""LiteLLM wrapper — single call site for all LLM interactions in Colophon.

Supports any provider LiteLLM understands:
  - anthropic/claude-haiku-4-5       (default; cloud, 200K context, ~$0.15/novel)
  - anthropic/claude-sonnet-4-6      (cloud, larger context headroom)
  - openai/gpt-5.4-mini              (cloud; cheaper than Haiku; set OPENAI_API_KEY)
  - openai/gpt-5.4-nano              (cloud; cheapest extraction baseline)
  - openrouter/z-ai/glm-5.2          (OpenRouter proxy; set OPENROUTER_API_KEY)
  - openrouter/deepseek/deepseek-r2  (OpenRouter proxy; very cheap at scale)
  - ollama/gemma4:26b-mlx-bf16       (local/Tailnet Ollama, set api_base + num_ctx)
  - ollama/gemma3:12b                 (local Ollama, no key required)

Custom Ollama endpoints (e.g. a Mac Studio on your Tailnet):
  Set api_base="http://100.x.x.x:11434" and num_ctx=262144 in LLMConfig.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import litellm

from colophon.config import LLMConfig

log = logging.getLogger(__name__)


def _recover_truncated_json(text: str) -> Any | None:
    """Best-effort recovery of a JSON response truncated by an output token limit.

    Scans backwards from the end to find the last complete object boundary,
    then closes any open array/object containers. Returns the parsed value on
    success, None if the fragment is unrecoverable.
    """
    # Find the last complete top-level closing brace/bracket we can trust.
    # Walk backwards looking for } that closes a top-level object inside an array.
    for end in range(len(text), 0, -1):
        candidate = text[:end]
        # Close any unclosed array/object nesting.
        depth_map = {"{": "}", "[": "]"}
        stack: list[str] = []
        in_str = False
        escape = False
        for ch in candidate:
            if escape:
                escape = False
                continue
            if ch == "\\" and in_str:
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch in ("{", "["):
                stack.append(depth_map[ch])
            elif ch in ("}", "]") and stack and stack[-1] == ch:
                stack.pop()
        if not stack:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        # Try closing all open containers and parsing.
        closing = "".join(reversed(stack))
        try:
            return json.loads(candidate + closing)
        except json.JSONDecodeError:
            continue
    return None


class LLMAdapter:
    def __init__(self, cfg: LLMConfig) -> None:
        self._cfg = cfg
        # Silently drop params a given provider doesn't support (e.g.
        # response_format on a model without JSON mode) instead of erroring.
        litellm.drop_params = True

    def _resolve_max_tokens(self) -> int | None:
        """Output-token ceiling to request, or None to use the provider default.

        An explicit config value wins. Otherwise ask LiteLLM for the model's
        documented max output; if the model is unknown (raises), return None so
        the request omits max_tokens and the provider applies its own default.
        """
        if self._cfg.max_output_tokens:
            return self._cfg.max_output_tokens
        try:
            return litellm.get_max_tokens(self._cfg.model)
        except Exception:
            return None

    def complete(
        self, system: str, user: str, response_format: dict[str, Any] | None = None
    ) -> str:
        """Send a single system+user turn; return the assistant text."""
        api_key = self._cfg.resolved_api_key()
        kwargs: dict[str, Any] = {
            "model": self._cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "timeout": self._cfg.timeout,
            "temperature": self._cfg.temperature,
        }
        max_tokens = self._resolve_max_tokens()
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if response_format is not None:
            kwargs["response_format"] = response_format
        if api_key:
            kwargs["api_key"] = api_key
        if self._cfg.api_base:
            kwargs["api_base"] = self._cfg.api_base
        # Ollama-specific: override the model's built-in context window.
        # LiteLLM forwards num_ctx into the options dict for Ollama requests.
        if self._cfg.num_ctx is not None:
            kwargs["num_ctx"] = self._cfg.num_ctx

        response = litellm.completion(**kwargs)
        msg = response.choices[0].message
        # Reasoning models (GLM, o1, DeepSeek-R1…) put the final answer in
        # `content` after the think block. If content is absent, fall back to
        # the raw reasoning text so callers always get a non-empty string.
        return msg.content or getattr(msg, "reasoning", None) or ""

    def complete_json(self, system: str, user: str) -> Any:
        """Like complete(), but parse and return the JSON from the response.

        Requests the provider's native JSON mode so the response is guaranteed
        parseable. Raises ValueError if the model returns non-JSON text that
        cannot be recovered. When the output is truncated mid-array (output
        token limit hit on large inputs), attempts to salvage complete objects
        from the partial response before giving up.
        """
        raw = self.complete(system, user, response_format={"type": "json_object"})
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]).strip()
        # Some models prefix JSON with a markdown horizontal rule (---).
        if text.startswith("---"):
            text = text.lstrip("-").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Output was truncated mid-stream (common when input fills most of the
        # context window and the entity list overflows max_completion_tokens).
        # Try to recover by closing the innermost open array/object.
        recovered = _recover_truncated_json(text)
        if recovered is not None:
            log.warning(
                "LLM response truncated at %d chars (hit output token limit); "
                "recovered partial JSON — tail entities for this chunk were lost. "
                "Reduce --chunk-chars or raise max_output_tokens to capture them.",
                len(text),
            )
            return recovered
        raise ValueError(f"LLM returned non-JSON response: {raw[:200]!r}")
