import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from models.recording import VoiceRecording


def test_take_roundtrip_and_status(make_profile, make_take, session):
    p = make_profile()
    tid = make_take(p, transcript="hello", duration_ms=1200).id
    session.expunge_all()
    got = session.get(VoiceRecording, tid)
    assert got.created_at is not None
    assert got.status == "transcribed"
    assert got.profile.phone_number == "+14155550100"


def test_status_failed_and_stuck(make_profile, make_take):
    p = make_profile()
    assert make_take(p, attempt=1, stt_error="boom").status == "failed"
    assert make_take(p, attempt=2).status == "stuck"


def test_attempt_unique_per_profile_and_step(make_profile, make_take, session):
    p = make_profile()
    make_take(p, step="story", attempt=1)
    make_take(p, step="availability", attempt=1)  # other step: fine
    with pytest.raises(IntegrityError):
        make_take(p, step="story", attempt=1)
    session.rollback()


def test_audio_is_deferred(make_profile, make_take, session):
    p = make_profile()
    tid = make_take(p).id
    session.expunge_all()
    got = session.get(VoiceRecording, tid)
    assert "audio" not in inspect(got).dict
    assert got.audio == b"fake-audio"  # loads on access


def test_deleting_profile_cascades_to_takes(make_profile, make_take, session):
    p = make_profile()
    make_take(p)
    session.delete(p)
    session.commit()
    assert VoiceRecording.query.count() == 0
