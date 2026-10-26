"""The LLM API key comes from config (vLLM on the DGX requires one); lab and
dev Ollama ignore it, so the default stays "ollama"."""
import importlib

import pytest

import config
from services import nlp_service


class StopAtClient(Exception):
    pass


def test_llm_api_key_reaches_client(app, monkeypatch):
    seen = {}

    def fake_openai(**kwargs):
        seen.update(kwargs)
        raise StopAtClient

    monkeypatch.setattr(nlp_service, "OpenAI", fake_openai)
    app.config["LLM_API_KEY"] = "vllm-secret"

    with pytest.raises(StopAtClient):
        nlp_service.extract_profile_data({"story": "I fix cars"})

    assert seen["api_key"] == "vllm-secret"


def test_llm_api_key_defaults_to_ollama(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    # Keep a developer's .env out of it.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
    try:
        assert importlib.reload(config).Config.LLM_API_KEY == "ollama"
    finally:
        monkeypatch.undo()
        importlib.reload(config)
