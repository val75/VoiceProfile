"""Tests for the completion-kwargs builder in nlp_service.

Isolates the one behavioral branch we care about: whether response_format is
sent. JSON mode must be omittable for engines whose guided-decoding backend is
unavailable (e.g. vLLM+outlines with a missing dep on the DGX).
"""

from services.nlp_service import _completion_kwargs


def test_json_mode_on_includes_response_format():
    kw = _completion_kwargs("m", [{"role": "user", "content": "hi"}], timeout=30, max_tokens=2048, json_mode=True)
    assert kw["response_format"] == {"type": "json_object"}


def test_json_mode_off_omits_response_format():
    kw = _completion_kwargs("m", [{"role": "user", "content": "hi"}], timeout=30, max_tokens=2048, json_mode=False)
    assert "response_format" not in kw


def test_completion_kwargs_carry_core_params():
    kw = _completion_kwargs("mymodel", [{"role": "user", "content": "hi"}], timeout=45, max_tokens=1024, json_mode=True)
    assert kw["model"] == "mymodel"
    assert kw["timeout"] == 45
    assert kw["max_tokens"] == 1024
    assert kw["temperature"] == 0.1
