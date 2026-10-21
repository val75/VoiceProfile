"""An unfinished profile is never rendered as a profile: the owner is sent back
into onboarding, and the public page / review form / photo 404 until completed."""
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


def test_review_cannot_be_posted_on_unfinished_profile(client, make_profile):
    p = make_profile(name=None)
    resp = client.post(f"/p/{p.id}/review/new", data={"rating": "5", "content": "great"})
    assert resp.status_code == 404
    assert Review.query.count() == 0
