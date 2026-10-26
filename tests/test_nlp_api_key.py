"""The LLM API key comes from config (vLLM on the DGX requires one); lab and
dev Ollama ignore it, so the default stays "ollama"."""
import logging
import os
import subprocess
import sys
from pathlib import Path

import httpx
import openai
import pytest

from services import nlp_service

REPO = Path(__file__).resolve().parent.parent


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


def test_llm_api_key_defaults_to_ollama():
    # A fresh interpreter, so reloading config can't leak into other tests;
    # load_dotenv is stubbed so a developer's .env can't set the key.
    env = {k: v for k, v in os.environ.items() if k != "LLM_API_KEY"}
    code = ("import dotenv; dotenv.load_dotenv = lambda *a, **kw: None; "
            "import config; print(config.Config.LLM_API_KEY)")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env,
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "ollama"


def test_rejected_key_fails_at_once_with_clear_log(app, monkeypatch, caplog):
    # A key mismatch (e.g. mid-rollout) is not transient: don't retry it, and
    # say what it is instead of "Unexpected LLM error".
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            request = httpx.Request("POST", "http://dgx/v1/chat/completions")
            raise openai.AuthenticationError(
                "Unauthorized", response=httpx.Response(401, request=request), body=None)

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(nlp_service, "OpenAI", FakeClient)

    with caplog.at_level(logging.ERROR), pytest.raises(nlp_service.ExtractionError):
        nlp_service.extract_profile_data({"story": "I fix cars"})

    assert len(calls) == 1
    assert "LLM_API_KEY" in caplog.text
