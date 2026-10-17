from datetime import datetime, timedelta, timezone

import pytest

from models.otp import OTPCode
from models.otp_request import OTPRequest
from models.profile import WorkerProfile
from models.recording import VoiceRecording
from models.review import Review
from services.profile_service import delete_profile, profile_footprint


@pytest.fixture
def two_workers(session, make_profile, make_take):
    def fill(phone):
        p = make_profile(phone)
        make_take(p, audio=b"x" * 1000)
        session.add_all([
            Review(profile_id=p.id, rating=5, content="great"),
            OTPCode(phone=phone, code_hash="h" * 64,
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)),
            OTPRequest(phone=phone, ip="203.0.113.5"),
        ])
        session.commit()
        return p
    return fill("+14155550100"), fill("+14155550199")


def test_footprint_and_delete(session, two_workers):
    target, other = two_workers
    assert profile_footprint(target) == {"reviews": 1, "recordings": 1, "recording_bytes": 1000,
                                         "otp_codes": 1, "otp_requests": 1}
    target_id = target.id
    counts = delete_profile(target)
    assert counts == {"reviews": 1, "recordings": 1, "otp_codes": 1, "otp_requests": 1}
    assert session.get(WorkerProfile, target_id) is None
    for model in (Review, VoiceRecording):
        assert model.query.count() == 1  # the other worker's row
    assert OTPCode.query.filter_by(phone="+14155550100").count() == 0
    assert OTPRequest.query.filter_by(phone="+14155550199").count() == 1
    assert session.get(WorkerProfile, other.id) is not None


def test_profile_without_phone_deletes_cleanly(session, make_profile, two_workers):  # Review Focus 3
    lonely = make_profile(phone=None)
    counts = delete_profile(lonely)
    assert counts["otp_codes"] == 0 and counts["otp_requests"] == 0
    assert OTPCode.query.count() == 2 and OTPRequest.query.count() == 2


def test_signed_in_worker_gets_404_after_delete(client, two_workers):
    target, _ = two_workers
    pid = target.id
    with client.session_transaction() as sess:
        sess["profile_id"] = pid
    delete_profile(target)
    assert client.get(f"/onboarding/{pid}/story").status_code == 404


def _run(app, *args, input=None):
    return app.test_cli_runner().invoke(args=["profile", "delete", *args], input=input)


def test_cli_by_phone_confirms(app, two_workers):
    aborted = _run(app, "--phone", "(415) 555-0100", input="n\n")
    assert aborted.exit_code == 1 and WorkerProfile.query.count() == 2
    assert "reviews: 1" in aborted.output and "recordings: 1" in aborted.output
    result = _run(app, "--phone", "(415) 555-0100", input="y\n")
    assert result.exit_code == 0 and "Deleted profile" in result.output
    assert WorkerProfile.query.filter_by(phone_number="+14155550100").count() == 0


def test_cli_by_id_yes(app, two_workers):
    _, other = two_workers
    assert _run(app, "--id", str(other.id), "--yes").exit_code == 0
    assert WorkerProfile.query.count() == 1


def test_cli_errors(app, two_workers):
    assert _run(app, "--yes").exit_code == 1                                   # neither
    assert _run(app, "--id", "1", "--phone", "4155550100", "--yes").exit_code == 1  # both
    assert _run(app, "--phone", "12", "--yes").exit_code == 1                  # invalid
    assert _run(app, "--id", "99999", "--yes").exit_code == 1                  # unknown


def test_delete_is_logged_on_the_app_logger(app, two_workers, caplog):
    import logging
    target, _ = two_workers
    pid = target.id
    with caplog.at_level(logging.INFO):
        delete_profile(target)
    # Only app.logger is raised to INFO in production; a module logger would be dropped.
    assert any(r.name == app.logger.name and f"Deleted profile {pid}" in r.getMessage()
               for r in caplog.records)
