"""stt_service: Whisper failures are logged with their cause, and the error
raised for the browser stays generic."""
import io
import logging

import pytest
import requests
from werkzeug.datastructures import FileStorage

from services import stt_service
from services.stt_service import SpeechToTextError, transcribe_audio


class FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


def audio():
    return FileStorage(stream=io.BytesIO(b"fake-audio"), filename="take.webm",
                       content_type="audio/webm")


@pytest.fixture
def whisper_config(app):
    app.config["WHISPER_URL"] = "http://whisper.test/transcribe"
    app.config["WHISPER_API_KEY"] = "k"


def test_non_200_is_logged_with_status_and_body(app, whisper_config, monkeypatch, caplog):
    body = '{"detail":"transcription failed: OSError: [Errno 28] No space left on device"}'
    monkeypatch.setattr(stt_service.requests, "post",
                        lambda *a, **kw: FakeResponse(500, body))

    with caplog.at_level(logging.ERROR), pytest.raises(SpeechToTextError) as exc:
        transcribe_audio(audio())

    assert "500" in caplog.text
    assert "No space left on device" in caplog.text
    # The browser gets the 502 JSON with str(e): no server internals in it.
    assert "No space left" not in str(exc.value)


def test_connection_error_is_logged(app, whisper_config, monkeypatch, caplog):
    def refuse(*a, **kw):
        raise requests.ConnectionError("Connection refused")

    monkeypatch.setattr(stt_service.requests, "post", refuse)

    with caplog.at_level(logging.ERROR), pytest.raises(SpeechToTextError):
        transcribe_audio(audio())

    assert "Connection refused" in caplog.text
