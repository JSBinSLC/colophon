"""Probe a model's limits and pricing before a run.

LiteLLM's static model DB covers Anthropic/OpenAI but not most OpenRouter models
(litellm.get_model_info raises for them), so for openrouter/* we query
OpenRouter's live /models endpoint and fall back to LiteLLM otherwise.

Used to (a) request the correct max output tokens — LiteLLM sends none for
OpenRouter models, leaving the provider default — and (b) preview chunk count
and cost before spending anything.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass

import litellm

log = logging.getLogger(__name__)

_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_openrouter_cache: dict[str, dict] | None = None


@dataclass
class ModelInfo:
    """Best-effort model metadata; any field may be None if unknown."""
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    input_cost_per_token: float | None = None
    output_cost_per_token: float | None = None


def _to_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _fetch_openrouter_models(api_key: str | None) -> dict[str, dict]:
    """Fetch and cache OpenRouter's model catalog, keyed by model id."""
    global _openrouter_cache
    if _openrouter_cache is not None:
        return _openrouter_cache
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    req = urllib.request.Request(_OPENROUTER_MODELS_URL, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (trusted URL)
        data = json.load(resp)
    _openrouter_cache = {m["id"]: m for m in data.get("data", [])}
    return _openrouter_cache


def probe_model(model: str, api_key: str | None = None) -> ModelInfo:
    """Return a model's limits and pricing, or an empty ModelInfo on any failure.

    Never raises — a probe failure must not block a repair; callers fall back to
    provider defaults.
    """
    try:
        if model.startswith("openrouter/"):
            model_id = model.split("/", 1)[1]
            entry = _fetch_openrouter_models(api_key).get(model_id)
            if not entry:
                return ModelInfo()
            pricing = entry.get("pricing", {})
            top = entry.get("top_provider") or {}
            return ModelInfo(
                max_input_tokens=entry.get("context_length"),
                max_output_tokens=(
                    top.get("max_completion_tokens") or entry.get("context_length")
                ),
                input_cost_per_token=_to_float(pricing.get("prompt")),
                output_cost_per_token=_to_float(pricing.get("completion")),
            )
        info = litellm.get_model_info(model)
        return ModelInfo(
            max_input_tokens=info.get("max_input_tokens"),
            max_output_tokens=info.get("max_output_tokens"),
            input_cost_per_token=info.get("input_cost_per_token"),
            output_cost_per_token=info.get("output_cost_per_token"),
        )
    except Exception as exc:
        log.info(
            "Model probe failed for %s (%s); using provider defaults",
            model, type(exc).__name__,
        )
        return ModelInfo()
