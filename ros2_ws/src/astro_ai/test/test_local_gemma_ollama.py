"""Ollama compatibility at the real ASTRO client boundary."""

import json
from unittest.mock import MagicMock, patch

import pytest

from astro_ai.local_gemma_client import LocalGemmaClient


def response(data):
    result = MagicMock()
    result.status = 200
    result.read.return_value = json.dumps(data).encode()
    result.__enter__.return_value = result
    return result


@pytest.mark.parametrize("installed, expected", [("gemma4:e2b", True), ("other:latest", False)])
def test_ollama_availability_requires_selected_model(installed, expected):
    client = LocalGemmaClient(base_url="http://127.0.0.1:11434", model_name="gemma4:e2b", backend="ollama")
    with patch("urllib.request.urlopen", return_value=response({"models": [{"name": installed}]})) as http:
        assert client.is_available() is expected
        assert http.call_args.args[0].full_url == "http://127.0.0.1:11434/api/tags"


@pytest.mark.parametrize("stream", [False, True])
def test_ollama_returns_answer_with_thinking_disabled(stream):
    client = LocalGemmaClient(base_url="http://127.0.0.1:11434", model_name="gemma4:e2b", backend="ollama")

    def serve(request, **kwargs):
        payload = json.loads(request.data)
        assert payload["reasoning_effort"] == "none"
        assert payload["model"] == "gemma4:e2b"
        assert request.full_url.endswith("/v1/chat/completions")
        result = response({"choices": [{"message": {"content": "Merhaba."}}]})
        result.__iter__.return_value = iter([
            b'data: {"choices":[{"delta":{"content":"Merhaba."},"finish_reason":"stop"}]}\n',
        ])
        return result

    with patch("urllib.request.urlopen", side_effect=serve):
        answer = "".join(client.stream("Selam")) if stream else client.generate("Selam")
        assert answer == "Merhaba."


def test_ollama_backend_can_be_selected_by_environment(monkeypatch):
    monkeypatch.setenv("LOCAL_GEMMA_BACKEND", "ollama")
    assert LocalGemmaClient().backend == "ollama"


def test_unknown_backend_is_rejected():
    with pytest.raises(ValueError):
        LocalGemmaClient(backend="ollam")
