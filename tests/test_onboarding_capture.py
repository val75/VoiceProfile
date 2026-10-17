import io
from unittest.mock import patch

import pytest

from extensions.database import db
from models.profile import WorkerProfile
from models.recording import VoiceRecording
from services.stt_service import SpeechToTextError

WHISPER = "blueprints.onboarding.routes.transcribe_audio"


def _echo(fs):
    return fs.read().decode()  # proves the upload was rewound before Whisper


@pytest.fixture
def worker(client, make_profile):
    p = make_profile()
    with client.session_transaction() as sess:
        sess["profile_id"] = p.id
    return p


def _post(client, pid, step="story", data=b"abc", **form):
    payload = {"audio": (io.BytesIO(data), "voice.webm", "audio/webm"), **form}
    return client.post(f"/onboarding/{pid}/{step}/transcribe", data=payload,
                       content_type="multipart/form-data")


def test_take_saved_then_filled(app, client, worker):
    app.config["VOICE_RECORDING_CAPTURE"] = True
    with patch(WHISPER, side_effect=_echo):
        resp = _post(client, worker.id, duration_ms="4200")
    assert resp.status_code == 200 and resp.get_json()["transcription"] == "abc"
    t = VoiceRecording.query.one()
    assert (t.transcript, t.duration_ms, t.audio, t.attempt) == ("abc", 4200, b"abc", 1)


def test_stt_failure_keeps_take_with_error(app, client, worker):
    app.config["VOICE_RECORDING_CAPTURE"] = True
    with patch(WHISPER, side_effect=SpeechToTextError("boom")):
        resp = _post(client, worker.id)
    assert resp.status_code == 502
    t = VoiceRecording.query.one()
    assert t.stt_error == "boom" and t.transcript is None and t.status == "failed"


def test_capture_error_leaves_worker_flow_identical(app, client, worker):
    app.config["VOICE_RECORDING_CAPTURE"] = True
    with patch(WHISPER, side_effect=_echo), \
         patch("services.recording_service._next_attempt", side_effect=RuntimeError("db")):
        resp = _post(client, worker.id)
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["success"] is True and body["transcription"] == "abc"
    assert body["confirm_url"].endswith(f"/onboarding/{worker.id}/story/confirm")
    assert db.session.get(WorkerProfile, worker.id).transcripts == {"story": "abc"}
    assert VoiceRecording.query.count() == 0


def test_capture_off_saves_nothing(client, worker):
    with patch(WHISPER, side_effect=_echo):
        assert _post(client, worker.id).status_code == 200
    assert VoiceRecording.query.count() == 0


@pytest.mark.parametrize("raw", ["", "abc", "-5", "1.5", "999999999999"])
def test_junk_duration_ignored(app, client, worker, raw):
    app.config["VOICE_RECORDING_CAPTURE"] = True
    with patch(WHISPER, side_effect=_echo):
        _post(client, worker.id, duration_ms=raw)
    assert VoiceRecording.query.one().duration_ms is None


def test_confirm_accept_with_edit_marks_take(app, client, worker):
    app.config["VOICE_RECORDING_CAPTURE"] = True
    with patch(WHISPER, side_effect=_echo):
        _post(client, worker.id)
    resp = client.post(f"/onboarding/{worker.id}/story/confirm",
                       json={"confirmed": True, "edited_text": "abc and more"})
    assert resp.status_code == 200
    t = VoiceRecording.query.one()
    assert t.accepted is True and t.edited_text == "abc and more"
    assert db.session.get(WorkerProfile, worker.id).transcripts["story"] == "abc and more"


def test_confirm_reject_marks_take_and_next_take_is_attempt_2(app, client, worker):
    app.config["VOICE_RECORDING_CAPTURE"] = True
    with patch(WHISPER, side_effect=_echo):
        _post(client, worker.id)
        client.post(f"/onboarding/{worker.id}/story/confirm", json={"confirmed": False})
        _post(client, worker.id)
    first, second = VoiceRecording.query.order_by(VoiceRecording.attempt).all()
    assert first.accepted is False and second.attempt == 2 and second.accepted is None


def test_empty_edit_rejected_before_marking(app, client, worker):
    app.config["VOICE_RECORDING_CAPTURE"] = True
    with patch(WHISPER, side_effect=_echo):
        _post(client, worker.id)
    resp = client.post(f"/onboarding/{worker.id}/story/confirm",
                       json={"confirmed": True, "edited_text": "   "})
    assert resp.status_code == 400
    assert VoiceRecording.query.one().accepted is None
