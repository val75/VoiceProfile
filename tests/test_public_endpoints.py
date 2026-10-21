"""Unauthenticated endpoints: the legacy ones are gone, and the one the public
review page needs (/voice/transcribe) is size-capped and rate-limited per IP."""
import io
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from models.profile import WorkerProfile
from models.transcribe_request import TranscribeRequest

WHISPER = "blueprints.voice_input.routes.transcribe_audio"


@pytest.mark.parametrize("method, path, kwargs", [
    ("post", "/profiles/", {"json": {"phone_number": "+14155550100",
                                     "onboarding_state": "completed"}}),
    ("get", "/profiles/", {}),
    ("get", "/profiles/{id}", {}),
    ("post", "/voice/upload", {"data": {"file": (io.BytesIO(b"abc"), "v.webm")},
                               "content_type": "multipart/form-data"}),
    ("get", "/voice/record", {}),
    ("post", "/builder/parse", {"json": {"text": "I am a welder"}}),
    ("get", "/onboarding/question/name", {}),
    ("post", "/onboarding/transcribe", {"data": {"audio": (io.BytesIO(b"abc"), "v.webm")},
                                        "content_type": "multipart/form-data"}),
])
def test_legacy_endpoints_are_gone(client, make_profile, method, path, kwargs):
    p = make_profile(onboarding_state="completed")
    before = WorkerProfile.query.count()
    resp = getattr(client, method)(path.format(id=p.id), **kwargs)
    assert resp.status_code in (404, 405)
    assert WorkerProfile.query.count() == before


def _transcribe(client, data=b"abc", ip="203.0.113.5"):
    return client.post("/voice/transcribe",
                       data={"audio": (io.BytesIO(data), "voice.webm", "audio/webm")},
                       content_type="multipart/form-data",
                       environ_base={"REMOTE_ADDR": ip})


def test_transcribe_still_works(client):
    with patch(WHISPER, return_value="five stars") as whisper:
        resp = _transcribe(client)
    assert resp.status_code == 200 and resp.get_json() == {"text": "five stars"}
    assert whisper.call_count == 1
    assert TranscribeRequest.query.count() == 1


def test_transcribe_rate_limited_per_ip(app, client):
    app.config["TRANSCRIBE_MAX_PER_IP_PER_HOUR"] = 2
    with patch(WHISPER, return_value="ok") as whisper:
        assert _transcribe(client).status_code == 200
        assert _transcribe(client).status_code == 200
        blocked = _transcribe(client)
        assert _transcribe(client, ip="198.51.100.7").status_code == 200  # other IP unaffected
    assert blocked.status_code == 429 and blocked.get_json()["error"]
    assert whisper.call_count == 3


def test_transcribe_window_expires(app, client, session):
    app.config["TRANSCRIBE_MAX_PER_IP_PER_HOUR"] = 1
    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    session.add(TranscribeRequest(ip="203.0.113.5", created_at=stale))
    session.commit()
    with patch(WHISPER, return_value="ok"):
        assert _transcribe(client).status_code == 200
    assert TranscribeRequest.query.count() == 1  # stale row cleaned up


def test_stale_rows_of_other_ips_are_pruned(client, session):
    # IPs that never come back must not leave their rows behind forever.
    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    session.add(TranscribeRequest(ip="198.51.100.7", created_at=stale))
    session.commit()
    with patch(WHISPER, return_value="ok"):
        assert _transcribe(client).status_code == 200
    assert [r.ip for r in TranscribeRequest.query.all()] == ["203.0.113.5"]


def test_transcribe_rejects_oversized_audio(app, client):
    app.config["TRANSCRIBE_MAX_BYTES"] = 1000  # whole request body, multipart overhead included
    with patch(WHISPER, return_value="ok") as whisper:
        resp = _transcribe(client, data=b"x" * 2000)
        assert _transcribe(client, data=b"x" * 100).status_code == 200
    assert resp.status_code == 413 and resp.get_json()["error"]
    assert whisper.call_count == 1
    assert TranscribeRequest.query.count() == 2  # the rejected upload still used up quota


def test_oversized_uploads_cannot_dodge_the_rate_limit(app, client):
    app.config.update(TRANSCRIBE_MAX_BYTES=1000, TRANSCRIBE_MAX_PER_IP_PER_HOUR=2)
    with patch(WHISPER) as whisper:
        codes = [_transcribe(client, data=b"x" * 2000).status_code for _ in range(3)]
    assert codes == [413, 413, 429]
    assert whisper.call_count == 0


def test_body_limit_is_scoped_to_transcribe(app, client, make_profile):
    # The cap is set per request, not app-wide: onboarding takes (up to 3 min) are unaffected.
    app.config["TRANSCRIBE_MAX_BYTES"] = 1000
    p = make_profile()
    with client.session_transaction() as sess:
        sess["profile_id"] = p.id
    with patch("blueprints.onboarding.routes.transcribe_audio", return_value="ok"):
        resp = client.post(f"/onboarding/{p.id}/story/transcribe",
                           data={"audio": (io.BytesIO(b"x" * 5000), "voice.webm", "audio/webm")},
                           content_type="multipart/form-data")
    assert resp.status_code == 200
