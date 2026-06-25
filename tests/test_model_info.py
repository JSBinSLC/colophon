"""Tests for the model-metadata probe."""
from __future__ import annotations

from unittest.mock import patch

from colophon.models.model_info import ModelInfo, probe_model

_FAKE_OPENROUTER = {
    "google/gemini-2.5-flash-lite": {
        "id": "google/gemini-2.5-flash-lite",
        "context_length": 1048576,
        "top_provider": {"max_completion_tokens": 65535},
        "pricing": {"prompt": "0.0000001", "completion": "0.0000004"},
    },
}


def test_probe_openrouter_parses_limits_and_pricing():
    with patch("colophon.models.model_info._fetch_openrouter_models", return_value=_FAKE_OPENROUTER):
        info = probe_model("openrouter/google/gemini-2.5-flash-lite")
    assert info.max_input_tokens == 1048576
    assert info.max_output_tokens == 65535
    assert info.input_cost_per_token == 1e-7
    assert info.output_cost_per_token == 4e-7


def test_probe_openrouter_unknown_model_returns_empty():
    with patch("colophon.models.model_info._fetch_openrouter_models", return_value=_FAKE_OPENROUTER):
        info = probe_model("openrouter/some/nonexistent-model")
    assert info == ModelInfo()


def test_probe_known_anthropic_model_via_litellm():
    # No network: LiteLLM's static DB knows this model.
    info = probe_model("anthropic/claude-haiku-4-5")
    assert info.max_output_tokens and info.max_output_tokens > 0
    assert info.input_cost_per_token and info.input_cost_per_token > 0


def test_probe_unknown_model_never_raises():
    # LiteLLM has a generic Ollama entry (local models are free → 0.0 cost).
    # The point of this test is that the probe doesn't raise.
    info = probe_model("ollama/some-local-model-litellm-doesnt-know")
    assert isinstance(info, ModelInfo)
    assert not info.input_cost_per_token  # 0.0 or None


def test_probe_network_failure_returns_empty():
    with patch(
        "colophon.models.model_info._fetch_openrouter_models",
        side_effect=OSError("network down"),
    ):
        info = probe_model("openrouter/google/gemini-2.5-flash-lite")
    assert info == ModelInfo()
