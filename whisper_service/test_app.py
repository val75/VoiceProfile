"""Tests for the Whisper API (whisper_service/app.py).

These need the service's deps (fastapi, python-multipart) plus httpx2 and
pytest, not the web app's venv, so the app's test run skips them:

    ~/whisper_service/venv/bin/pip install pytest httpx2
    ~/whisper_service/venv/bin/python -m pytest whisper_service/test_app.py

The real whisper module is replaced by a stub, so no model is loaded.
"""
import importlib.util
import os
import sys
import types

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("multipart")
from fastapi.testclient import TestClient  # noqa: E402

APP_PATH = os.path.join(os.path.dirname(__file__), "app.py")
KEY = "test-whisper-key"


class FakeModel:
    def __init__(self):
        self.error = None

    def transcribe(self, path):
        if self.error:
            raise self.error
        return {"text": "hello", "language": "en"}


def load_app(monkeypatch, key=KEY):
    """Import app.py fresh with a stub whisper module and the given key."""
    fake_whisper = types.ModuleType("whisper")
    fake_whisper.load_model = lambda name: FakeModel()
    monkeypatch.setitem(sys.modules, "whisper", fake_whisper)
    if key is None:
        monkeypatch.delenv("WHISPER_API_KEY", raising=False)
    else:
        monkeypatch.setenv("WHISPER_API_KEY", key)
    # Load by path: "app" would collide with the web app's app.py.
    spec = importlib.util.spec_from_file_location("whisper_app_under_test", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tmp_tempdir(monkeypatch, tmp_path):
    """Point tempfile at an empty dir so leaked temp files are visible."""
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    return tmp_path


def post_audio(client, headers=None):
    return client.post(
        "/transcribe",
        files={"file": ("take.webm", b"fake-audio", "audio/webm")},
        headers=headers or {},
    )


def test_refuses_to_start_without_key(monkeypatch):
    with pytest.raises(RuntimeError, match="WHISPER_API_KEY"):
        load_app(monkeypatch, key=None)


def test_refuses_to_start_with_empty_key(monkeypatch):
    with pytest.raises(RuntimeError, match="WHISPER_API_KEY"):
        load_app(monkeypatch, key="")


def test_missing_key_is_401(monkeypatch):
    client = TestClient(load_app(monkeypatch).app)
    assert post_audio(client).status_code == 401


def test_wrong_key_is_401(monkeypatch):
    client = TestClient(load_app(monkeypatch).app)
    assert post_audio(client, {"X-API-Key": "wrong"}).status_code == 401


def test_right_key_transcribes(monkeypatch, tmp_tempdir):
    client = TestClient(load_app(monkeypatch).app)
    resp = post_audio(client, {"X-API-Key": KEY})
    assert resp.status_code == 200
    assert resp.json() == {"text": "hello", "language": "en"}
    assert list(tmp_tempdir.iterdir()) == []


def test_key_is_checked_before_the_body_is_parsed(monkeypatch):
    # A body that can't be parsed gets 400 from FastAPI once it's read.
    # Without the key, the request must be refused before anything is read
    # or spooled to disk.
    client = TestClient(load_app(monkeypatch).app)
    resp = client.post(
        "/transcribe",
        content=b"not multipart",
        headers={"Content-Type": "multipart/form-data"},
    )
    assert resp.status_code == 401


def test_failed_transcribe_returns_json_500_and_removes_temp_file(monkeypatch, tmp_tempdir):
    module = load_app(monkeypatch)
    module.model.error = RuntimeError("ffmpeg failed")
    client = TestClient(module.app, raise_server_exceptions=False)

    resp = post_audio(client, {"X-API-Key": KEY})

    assert resp.status_code == 500
    assert resp.json() == {"detail": "transcription failed: RuntimeError: ffmpeg failed"}
    assert list(tmp_tempdir.iterdir()) == []


def test_failed_write_returns_json_500_and_removes_temp_file(monkeypatch, tmp_tempdir):
    # The 2026-10-25 outage: the disk was full, so writing the upload failed.
    module = load_app(monkeypatch)

    async def disk_full(self, size=-1):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("starlette.datastructures.UploadFile.read", disk_full)
    client = TestClient(module.app, raise_server_exceptions=False)

    resp = post_audio(client, {"X-API-Key": KEY})

    assert resp.status_code == 500
    assert "No space left on device" in resp.json()["detail"]
    assert list(tmp_tempdir.iterdir()) == []
