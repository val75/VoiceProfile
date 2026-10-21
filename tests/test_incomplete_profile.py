"""An unfinished profile is never rendered as a profile: the owner is sent back
into onboarding, and the public page / review form / photo 404 until completed."""
import io
from unittest.mock import patch

import pytest

from models.review import Review


@pytest.fixture
def login(client):
    def _login(profile):
        with client.session_transaction() as sess:
            sess["profile_id"] = profile.id
        return profile
    return _login


@pytest.mark.parametrize("state, step", [
    ("intro", "intro"),
    (None, "intro"),
    ("name", "name"),
    ("name_confirm", "name"),
    ("story", "story"),
    ("availability", "availability"),
    ("review", "review"),
])
def test_owner_view_of_unfinished_profile_resumes_onboarding(client, make_profile, login,
                                                             state, step):
    p = login(make_profile(name=None, onboarding_state=state))
    resp = client.get(f"/profiles/{p.id}/view")
    assert resp.status_code == 302
    assert resp.headers["Location"] == f"/onboarding/{p.id}/{step}"


def test_owner_view_of_completed_profile_renders(client, make_profile, login):
    p = login(make_profile(onboarding_state="completed"))
    assert client.get(f"/profiles/{p.id}/view").status_code == 200


def test_home_page_continue_link_lands_in_onboarding(client, make_profile, login):
    p = login(make_profile(name=None))  # abandoned at intro, session cookie still alive
    resp = client.get("/", follow_redirects=False)
    assert "Continue" in resp.get_data(as_text=True)
    resp = client.get(f"/profiles/{p.id}/view", follow_redirects=True)
    assert resp.request.path == f"/onboarding/{p.id}/intro"


@pytest.mark.parametrize("path", [
    "/p/{id}",
    "/p/{id}/review/new",
    "/p/{id}/review/thanks",
    "/profiles/{id}/photo",
])
def test_public_pages_404_until_completed(client, make_profile, path):
    p = make_profile(name=None, photo=b"jpeg", photo_mime="image/jpeg")
    assert client.get(path.format(id=p.id)).status_code == 404


@pytest.mark.parametrize("path", [
    "/p/{id}",
    "/p/{id}/review/new",
    "/p/{id}/review/thanks",
    "/profiles/{id}/photo",
])
def test_public_pages_served_once_completed(client, make_profile, path):
    p = make_profile(onboarding_state="completed", photo=b"jpeg", photo_mime="image/jpeg")
    assert client.get(path.format(id=p.id)).status_code == 200


def _record(client, pid, step, heard="Ana Pop"):
    url = f"/onboarding/{pid}/name/transcribe" if step == "name" \
        else f"/onboarding/{pid}/{step}/transcribe"
    with patch("blueprints.onboarding.routes.transcribe_audio", return_value=heard):
        return client.post(url, data={"audio": (io.BytesIO(b"abc"), "voice.webm", "audio/webm")},
                           content_type="multipart/form-data")


@pytest.mark.parametrize("step, confirm", [
    ("name", {"confirmed": True}),
    ("name", {"confirmed": False}),
    ("story", {"confirmed": True}),
    ("story", {"confirmed": False}),
])
def test_rerecording_a_step_keeps_a_completed_profile_public(client, make_profile, login,
                                                             step, confirm):
    # e.g. Edit profile -> "Re-record story": the profile must stay live while it's edited.
    p = login(make_profile(onboarding_state="completed"))
    assert _record(client, p.id, step).status_code == 200
    confirm_url = f"/onboarding/{p.id}/{step}/confirm"
    assert client.post(confirm_url, json=confirm).status_code == 200
    assert p.onboarding_state == "completed"
    assert client.get(f"/p/{p.id}").status_code == 200
    assert client.get(f"/profiles/{p.id}/view").status_code == 200


def _public_name(client, pid):
    return client.get(f"/p/{pid}").get_data(as_text=True)


def test_rerecorded_name_is_not_saved_until_confirmed(client, make_profile, login):
    p = login(make_profile(name="Maria Lopez", onboarding_state="completed"))
    resp = _record(client, p.id, "name", heard="MY NAME IS ana pop.")
    assert resp.get_json()["name"] == "Ana Pop"  # still shown to the worker to confirm
    assert p.name == "Maria Lopez"
    assert "Maria Lopez" in _public_name(client, p.id)


def test_rejected_name_keeps_the_old_one(client, make_profile, login):
    p = login(make_profile(name="Maria Lopez", onboarding_state="completed"))
    _record(client, p.id, "name", heard="Ana Pop")
    client.post(f"/onboarding/{p.id}/name/confirm", json={"confirmed": False})
    assert p.name == "Maria Lopez"
    assert "Maria Lopez" in _public_name(client, p.id)


def test_accepted_name_is_saved_cleaned(client, make_profile, login):
    p = login(make_profile(name="Maria Lopez", onboarding_state="completed"))
    _record(client, p.id, "name", heard="MY NAME IS ana pop.")
    client.post(f"/onboarding/{p.id}/name/confirm", json={"confirmed": True})
    assert p.name == "Ana Pop"


def test_edited_name_wins_over_the_transcript(client, make_profile, login):
    p = login(make_profile(name=None, onboarding_state="name"))
    _record(client, p.id, "name", heard="Anna Pope")
    client.post(f"/onboarding/{p.id}/name/confirm",
                json={"confirmed": True, "edited_text": "  Ana Pop "})
    assert p.name == "Ana Pop"


def test_confirm_without_a_recorded_name_is_rejected(client, make_profile, login):
    p = login(make_profile(name=None, onboarding_state="name"))
    resp = client.post(f"/onboarding/{p.id}/name/confirm", json={"confirmed": True})
    assert resp.status_code == 400
    assert p.onboarding_state == "name"


@pytest.mark.parametrize("heard", ["", "...", "word " * 40])
def test_empty_or_overlong_name_take_is_refused(client, make_profile, login, heard):
    p = login(make_profile(name="Maria Lopez", onboarding_state="completed"))
    resp = _record(client, p.id, "name", heard=heard)
    assert resp.status_code == 400 and resp.get_json()["error"]
    # Nothing held: confirming now can't save it.
    assert client.post(f"/onboarding/{p.id}/name/confirm",
                       json={"confirmed": True}).status_code == 400
    assert p.name == "Maria Lopez"


def test_failed_take_drops_an_earlier_pending_one(client, make_profile, login):
    p = login(make_profile(name="Maria Lopez", onboarding_state="completed"))
    _record(client, p.id, "name", heard="Ana Pop")
    _record(client, p.id, "name", heard="word " * 40)
    assert client.post(f"/onboarding/{p.id}/name/confirm",
                       json={"confirmed": True}).status_code == 400
    assert p.name == "Maria Lopez"


def test_overlong_edited_name_is_refused(client, make_profile, login):
    p = login(make_profile(name=None, onboarding_state="name"))
    _record(client, p.id, "name", heard="Ana Pop")
    resp = client.post(f"/onboarding/{p.id}/name/confirm",
                       json={"confirmed": True, "edited_text": "x" * 121})
    assert resp.status_code == 400 and resp.get_json()["error"]
    assert p.name is None


def test_unfinished_profile_still_advances(client, make_profile, login):
    p = login(make_profile(name=None, onboarding_state="name"))
    _record(client, p.id, "name")
    assert p.onboarding_state == "name_confirm"
    client.post(f"/onboarding/{p.id}/name/confirm", json={"confirmed": True})
    assert p.onboarding_state == "story"


LIVE = {"summary": "Welder, 10 years"}
FRESH = {"summary": "Cook, 2 years"}
EXTRACT = "blueprints.onboarding.routes.extract_profile_data"


def _confirm_availability(client, pid, **extract):
    with patch(EXTRACT, **extract):
        return client.post(f"/onboarding/{pid}/availability/confirm", json={"confirmed": True})


def _review_page_data(client, pid, query=""):
    return client.get(f"/onboarding/{pid}/review{query}").get_data(as_text=True)


def test_reedit_extraction_waits_for_the_review_save(client, make_profile, login):
    p = login(make_profile(onboarding_state="completed", profile_data=LIVE,
                           transcripts={"story": "I cook", "availability": "weekends"}))
    resp = _confirm_availability(client, p.id, return_value=FRESH)
    assert resp.get_json()["next_url"] == f"/onboarding/{p.id}/review?draft=1"
    assert p.profile_data == LIVE and p.profile_data_draft == FRESH
    assert "Welder" in _public_name(client, p.id)
    assert "Cook, 2 years" in _review_page_data(client, p.id, "?draft=1")

    resp = client.post(f"/onboarding/{p.id}/review", json=FRESH)
    assert resp.status_code == 200
    assert p.profile_data == FRESH and p.profile_data_draft is None
    assert "Cook" in _public_name(client, p.id)


def test_reedit_extraction_failure_leaves_the_public_profile(client, make_profile, login):
    from services.nlp_service import ExtractionError
    p = login(make_profile(onboarding_state="completed", profile_data=LIVE,
                           transcripts={"story": "I cook", "availability": "weekends"}))
    _confirm_availability(client, p.id, side_effect=ExtractionError("LLM down"))
    assert p.profile_data == LIVE
    assert "extraction_error" in p.profile_data_draft
    assert "Welder" in _public_name(client, p.id)
    # The review page offers a retry over the live data, not an empty form to save.
    page = _review_page_data(client, p.id, "?draft=1")
    assert "We had trouble extracting" in page and "Welder" in page


def test_edit_profile_ignores_an_abandoned_draft(client, make_profile, login):
    p = login(make_profile(onboarding_state="completed", profile_data=LIVE,
                           profile_data_draft=FRESH))
    page = _review_page_data(client, p.id)  # Edit profile's link has no draft flag
    assert "Welder" in page and "Cook" not in page


def test_an_empty_draft_is_still_the_draft(client, make_profile, login):
    p = login(make_profile(onboarding_state="completed", profile_data=LIVE,
                           profile_data_draft={}))
    assert "Welder" not in _review_page_data(client, p.id, "?draft=1")


def test_failed_name_take_drops_an_earlier_pending_one(client, make_profile, login):
    from services.stt_service import SpeechToTextError
    p = login(make_profile(name="Maria Lopez", onboarding_state="completed"))
    _record(client, p.id, "name", heard="Ana Pop")
    with patch("blueprints.onboarding.routes.transcribe_audio",
               side_effect=SpeechToTextError("timeout")):
        resp = client.post(f"/onboarding/{p.id}/name/transcribe",
                           data={"audio": (io.BytesIO(b"abc"), "voice.webm", "audio/webm")},
                           content_type="multipart/form-data")
    assert resp.status_code == 502
    assert client.post(f"/onboarding/{p.id}/name/confirm",
                       json={"confirmed": True}).status_code == 400
    assert p.name == "Maria Lopez"


def test_reedit_re_extract_goes_to_the_draft(client, make_profile, login):
    p = login(make_profile(onboarding_state="completed", profile_data=LIVE,
                           transcripts={"story": "I cook"}))
    with patch(EXTRACT, return_value=FRESH):
        resp = client.post(f"/onboarding/{p.id}/review/re-extract")
    assert resp.get_json()["profile_data"] == FRESH
    assert p.profile_data == LIVE and p.profile_data_draft == FRESH


def test_first_time_extraction_writes_profile_data(client, make_profile, login):
    p = login(make_profile(onboarding_state="availability",
                           transcripts={"story": "I cook", "availability": "weekends"}))
    _confirm_availability(client, p.id, return_value=FRESH)
    assert p.profile_data == FRESH and p.profile_data_draft is None
    assert p.onboarding_state == "review"


def test_review_cannot_be_posted_on_unfinished_profile(client, make_profile):
    p = make_profile(name=None)
    resp = client.post(f"/p/{p.id}/review/new", data={"rating": "5", "content": "great"})
    assert resp.status_code == 404
    assert Review.query.count() == 0
