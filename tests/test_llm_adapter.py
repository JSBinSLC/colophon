"""Unit tests for LLMAdapter — verifies how we call the provider."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from colophon.config import LLMConfig
from colophon.models.llm_adapter import LLMAdapter, _recover_truncated_json


def _fake_response(content=None, reasoning=None):
    """Mimic the litellm ModelResponse shape the adapter reads."""
    message = SimpleNamespace(content=content, reasoning=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_complete_json_requests_json_mode_and_temperature():
    cfg = LLMConfig(model="anthropic/claude-haiku-4-5", api_key="k")
    adapter = LLMAdapter(cfg)

    with patch("colophon.models.llm_adapter.litellm.completion") as mock_completion:
        mock_completion.return_value = _fake_response(content='{"characters": []}')
        adapter.complete_json("sys", "usr")

    kwargs = mock_completion.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["temperature"] == 0.0
    # Known Anthropic model → litellm resolves a concrete max output ceiling.
    assert kwargs["max_tokens"] > 0


def test_temperature_override_is_forwarded():
    cfg = LLMConfig(model="anthropic/claude-haiku-4-5", api_key="k", temperature=0.7)
    adapter = LLMAdapter(cfg)

    with patch("colophon.models.llm_adapter.litellm.completion") as mock_completion:
        mock_completion.return_value = _fake_response(content="hi")
        adapter.complete("sys", "usr")

    assert mock_completion.call_args.kwargs["temperature"] == 0.7


def test_unknown_model_omits_max_tokens():
    # A model litellm can't resolve must not send a max_tokens (let provider default).
    cfg = LLMConfig(model="openrouter/google/gemini-2.5-flash-lite", api_key="k")
    adapter = LLMAdapter(cfg)

    with patch("colophon.models.llm_adapter.litellm.completion") as mock_completion:
        mock_completion.return_value = _fake_response(content="hi")
        adapter.complete("sys", "usr")

    assert "max_tokens" not in mock_completion.call_args.kwargs


def test_explicit_max_output_tokens_wins():
    cfg = LLMConfig(
        model="openrouter/google/gemini-2.5-flash-lite", api_key="k", max_output_tokens=8000
    )
    adapter = LLMAdapter(cfg)

    with patch("colophon.models.llm_adapter.litellm.completion") as mock_completion:
        mock_completion.return_value = _fake_response(content="hi")
        adapter.complete("sys", "usr")

    assert mock_completion.call_args.kwargs["max_tokens"] == 8000


def test_reasoning_fallback_when_content_empty():
    cfg = LLMConfig(model="openrouter/z-ai/glm-5.2", api_key="k")
    adapter = LLMAdapter(cfg)

    with patch("colophon.models.llm_adapter.litellm.completion") as mock_completion:
        mock_completion.return_value = _fake_response(content=None, reasoning="thought text")
        assert adapter.complete("sys", "usr") == "thought text"


def test_complete_json_recovers_truncated_response():
    cfg = LLMConfig(model="anthropic/claude-haiku-4-5", api_key="k")
    adapter = LLMAdapter(cfg)
    # Response cut off mid-array (output token limit) — second object incomplete.
    truncated = '{"characters": [{"canonical": "Kirk", "variants": [], "occurrences": 3}, {"canonical": "Spo'

    with patch("colophon.models.llm_adapter.litellm.completion") as mock_completion:
        mock_completion.return_value = _fake_response(content=truncated)
        result = adapter.complete_json("sys", "usr")

    assert result["characters"][0]["canonical"] == "Kirk"


def test_complete_json_raises_on_unrecoverable():
    cfg = LLMConfig(model="anthropic/claude-haiku-4-5", api_key="k")
    adapter = LLMAdapter(cfg)

    with patch("colophon.models.llm_adapter.litellm.completion") as mock_completion:
        mock_completion.return_value = _fake_response(content="not json at all")
        with pytest.raises(ValueError):
            adapter.complete_json("sys", "usr")


def test_recover_truncated_json_closes_open_containers():
    assert _recover_truncated_json('{"a": [1, 2, 3') == {"a": [1, 2, 3]}
    # Complete objects are preserved; a trailing incomplete one collapses to {}
    # (harmless — the pipeline discards entries without a canonical name).
    recovered = _recover_truncated_json('{"a": [{"b": 1}, {"b": 2}, {"b"')
    assert recovered["a"][:2] == [{"b": 1}, {"b": 2}]
    assert _recover_truncated_json("totally broken {[") is None
