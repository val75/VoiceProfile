import io
import logging
from unittest.mock import patch

from werkzeug.datastructures import FileStorage

from extensions.database import db
from models.recording import VoiceRecording
from services.recording_service import mark_decision, record_result, save_take

DATA = b"0123456789"


def _upload(data=DATA, content_type="audio/webm;codecs=opus"):
    return FileStorage(stream=io.BytesIO(data), filename="voice.webm", content_type=content_type)


def _on(app, **cfg):
    app.config["VOICE_RECORDING_CAPTURE"] = True
    app.config.update(cfg)


def test_capture_off_saves_nothing(app, make_profile):
    p = make_profile()
    up = _upload()
    assert save_take(p.id, "story", up, 1000) is None
    assert VoiceRecording.query.count() == 0
    assert up.read() == DATA


def test_save_take_stores_take_and_rewinds_upload(app, make_profile):
    _on(app)
    p = make_profile()
    up = _upload()
    take_id = save_take(p.id, "story", up, 4200)
    assert up.read() == DATA  # Whisper reads the same upload next
    t = db.session.get(VoiceRecording, take_id)
    assert (t.step, t.attempt, t.size_bytes, t.duration_ms) == ("story", 1, len(DATA), 4200)
    assert t.mime_type == "audio/webm;codecs=opus"
    assert t.audio == DATA and t.accepted is None and t.status == "stuck"


def test_attempts_count_per_step(app, make_profile):
    _on(app)
    p = make_profile()
    a = save_take(p.id, "story", _upload())
    b = save_take(p.id, "story", _upload())
    c = save_take(p.id, "availability", _upload())
    attempts = {i: db.session.get(VoiceRecording, i).attempt for i in (a, b, c)}
    assert attempts == {a: 1, b: 2, c: 1}


def test_over_cap_not_saved(app, make_profile, caplog):
    _on(app, VOICE_RECORDING_MAX_BYTES=5)
    p = make_profile()
    up = _upload()
    with caplog.at_level(logging.WARNING):
        assert save_take(p.id, "story", up) is None
    assert VoiceRecording.query.count() == 0
    assert up.read() == DATA
    assert any("over cap" in r.getMessage() for r in caplog.records)


def test_db_error_is_swallowed_and_session_clean(app, make_profile):
    _on(app)
    p = make_profile()
    up = _upload()
    with patch("services.recording_service._next_attempt", side_effect=RuntimeError("db down")):
        assert save_take(p.id, "story", up) is None
    assert not db.session.new and not db.session.dirty
    assert VoiceRecording.query.count() == 0
    assert up.read() == DATA


def test_attempt_clash_retries_once(app, make_profile, make_take):
    _on(app)
    p = make_profile()
    make_take(p, attempt=1)
    with patch("services.recording_service._next_attempt", side_effect=[1, 2]):
        take_id = save_take(p.id, "story", _upload())
    assert db.session.get(VoiceRecording, take_id).attempt == 2


def test_profile_gone_is_swallowed(app):
    _on(app)
    assert save_take(9999, "story", _upload()) is None  # FK violation (Review Focus 5)
    assert VoiceRecording.query.count() == 0


def test_record_result(app, make_profile, make_take):
    p = make_profile()
    ok, bad = make_take(p, attempt=1), make_take(p, attempt=2)
    record_result(ok.id, transcript="hello")
    record_result(bad.id, error="Whisper service unreachable")
    record_result(None, transcript="ignored")
    assert db.session.get(VoiceRecording, ok.id).status == "transcribed"
    assert db.session.get(VoiceRecording, bad.id).stt_error == "Whisper service unreachable"


def test_mark_decision_latest_undecided_only(app, make_profile, make_take):
    _on(app)
    p = make_profile()
    old = make_take(p, attempt=1, transcript="first")
    new = make_take(p, attempt=2, transcript=" I cook. ")
    mark_decision(p.id, "story", accepted=True, edited_text="I cook.")  # same text after strip
    assert db.session.get(VoiceRecording, old.id).accepted is None
    got = db.session.get(VoiceRecording, new.id)
    assert got.accepted is True and got.decided_at is not None and got.edited_text is None
    mark_decision(p.id, "story", accepted=False)  # already decided -> ignored
    assert db.session.get(VoiceRecording, new.id).accepted is True


def test_mark_decision_stores_real_edit_and_reject(app, make_profile, make_take):
    _on(app)
    p = make_profile()
    s = make_take(p, step="story", transcript="I cook")
    a = make_take(p, step="availability", transcript="weekends")
    mark_decision(p.id, "story", accepted=True, edited_text="I cook and clean")
    mark_decision(p.id, "availability", accepted=False, edited_text="ignored on reject")
    assert db.session.get(VoiceRecording, s.id).edited_text == "I cook and clean"
    rejected = db.session.get(VoiceRecording, a.id)
    assert rejected.accepted is False and rejected.edited_text is None


def test_mark_decision_noop_when_capture_off(app, make_profile, make_take):
    p = make_profile()
    t = make_take(p, transcript="x")
    mark_decision(p.id, "story", accepted=True)
    assert db.session.get(VoiceRecording, t.id).accepted is None


SECRET = "SECRET-TRANSCRIPT-TEXT"


def _db_error():
    # SQLAlchemy errors embed bound parameters in their text.
    return RuntimeError(f"(psycopg2.OperationalError) [parameters: {{'transcript': '{SECRET}'}}]")


def test_failure_logs_never_contain_worker_text(app, make_profile, make_take, caplog):
    _on(app)
    p = make_profile()
    t = make_take(p, transcript="x")
    with caplog.at_level(logging.DEBUG), \
         patch.object(db.session, "commit", side_effect=_db_error()):
        record_result(t.id, transcript=SECRET)
        mark_decision(p.id, "story", accepted=True, edited_text=SECRET)
        save_take(p.id, "story", _upload(SECRET.encode()))
    assert caplog.records, "failures should still be logged"
    assert SECRET not in caplog.text
