import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from extensions.database import db
from models.profile import WorkerProfile
from models.recording import VoiceRecording
from models.review import Review
from services.profile_service import (
    delete_confirmation_code, profile_counts, search_profiles,
)
from services.recording_service import FilterError
from services.timezones import db_local_to_admin, db_zone

SECRETS = ("SECRET-JOB", "SECRET-AVAIL", "SECRET-TRANSCRIPT", "SECRET-REVIEW")


@pytest.fixture
def admin(client):
    client.get("/admin/login")  # dev fallback: debug + loopback
    return client


@pytest.fixture
def review(session):
    def _add(profile, content="great"):
        session.add(Review(profile_id=profile.id, rating=5, content=content))
        session.commit()
    return _add


@pytest.fixture
def population(make_profile, make_take, review):
    """3 completed (2 with reviews), 4 incomplete (1 extraction error)."""
    done = [make_profile(f"+1415555010{i}", name=f"Done {i}", onboarding_state="completed")
            for i in range(3)]
    review(done[0])
    review(done[0])
    review(done[1])
    make_profile("+14155550200", name="Maria Lopez", onboarding_state="story")
    make_profile("+14155550201", name="Nina", onboarding_state="name_confirm")
    make_profile("+14155550202", name=None, onboarding_state="name")
    make_profile("+14155550203", name="Errol", onboarding_state="review",
                 profile_data={"extraction_error": "LLM down"})
    make_take(done[2], attempt=1)
    make_take(done[2], attempt=2)
    return done


def _ids(**kw):
    return [r.id for r in search_profiles(**kw).all()]


# --- service -----------------------------------------------------------------

def test_counts(population):
    c = profile_counts()
    assert (c["total"], c["completed"], c["incomplete"]) == (7, 3, 4)
    assert c["stopped_at"] == {"name": 2, "story": 1, "review": 1}  # name_confirm -> name
    assert c["extraction_errors"] == 1
    assert c["with_reviews"] == 2


def test_counts_empty_db(app):
    c = profile_counts()
    assert (c["total"], c["completed"], c["incomplete"], c["with_reviews"]) == (0, 0, 0, 0)
    assert c["stopped_at"] == {}


def test_rows_carry_admin_details_only(population, make_profile):
    make_profile("+14155550300", name="Pic", photo=b"jpeg", photo_mime="image/jpeg")
    rows = {r.name: r for r in search_profiles().all()}
    assert rows["Done 0"].review_count == 2 and rows["Done 2"].recording_count == 2
    assert bool(rows["Pic"].has_photo) and not bool(rows["Done 0"].has_photo)
    assert bool(rows["Errol"].extraction_error) and not bool(rows["Maria Lopez"].extraction_error)
    assert not hasattr(rows["Done 0"], "profile_data") and not hasattr(rows["Done 0"], "transcripts")


def test_newest_first(make_profile):
    a = make_profile("+14155550100", created_at=datetime(2026, 10, 1))
    b = make_profile("+14155550101", created_at=datetime(2026, 10, 2))
    c = make_profile("+14155550102", created_at=datetime(2026, 10, 2))  # tie -> id desc
    assert _ids() == [c.id, b.id, a.id]


def test_search_by_name(population):
    assert [r.name for r in search_profiles(q="maria").all()] == ["Maria Lopez"]
    assert len(_ids(q="done")) == 3
    assert _ids(q="%") == [] and _ids(q="_") == []  # LIKE wildcards are literal


def test_search_by_phone_digits(population):
    assert [r.name for r in search_profiles(q="0200").all()] == ["Maria Lopez"]
    assert [r.name for r in search_profiles(q="(415) 555-0201").all()] == ["Nina"]
    assert [r.name for r in search_profiles(q="+1 415 555 0203").all()] == ["Errol"]
    assert len(_ids(q="020")) == 4 and len(_ids(q="555")) == 7  # any length of digits
    assert [r.name for r in search_profiles(q="5")] != []


def test_search_with_letters_is_a_name_search(make_profile):
    make_profile("+14155550101", name="Worker 01")
    make_profile("+14155550102", name="Other")
    assert [r.name for r in search_profiles(q="Worker 01")] == ["Worker 01"]


def test_status_and_review_filters(population):
    assert len(_ids(status="completed")) == 3 and len(_ids(status="incomplete")) == 4
    assert len(_ids(reviews="has")) == 2 and len(_ids(reviews="none")) == 5
    assert len(_ids(status="completed", reviews="none")) == 1


def test_bad_filters_raise(app):
    with pytest.raises(FilterError, match="status"):
        search_profiles(status="active")
    with pytest.raises(FilterError, match="reviews"):
        search_profiles(reviews="some")


def test_delete_confirmation_code(make_profile):
    assert delete_confirmation_code(make_profile("+14155550187")) == "0187"
    nophone = make_profile(phone=None)
    assert delete_confirmation_code(nophone) == str(nophone.id)


def test_db_zone_and_conversion(app):
    assert db_zone() is timezone.utc  # SQLite's CURRENT_TIMESTAMP is UTC
    app.config["ADMIN_TIMEZONE"] = "America/Los_Angeles"
    pacific = ZoneInfo("America/Los_Angeles")
    assert db_local_to_admin(datetime(2026, 10, 17, 11, 48), pacific).hour == 11  # DB in LA
    assert db_local_to_admin(datetime(2026, 10, 17, 18, 48), timezone.utc).hour == 11
    assert db_local_to_admin(None, pacific) is None


# --- list page ---------------------------------------------------------------

def test_requires_admin(client, make_profile):
    p = make_profile()
    for url in ("/admin/profiles", f"/admin/profiles/{p.id}/delete"):
        resp = client.get(url)
        assert resp.status_code == 302 and "/admin/login" in resp.headers["Location"]
    with client.session_transaction() as sess:
        sess["profile_id"] = p.id  # a signed-in worker is not an admin
    assert client.get("/admin/profiles").status_code == 302
    resp = client.post(f"/admin/profiles/{p.id}/delete", data={"confirm": "0100"})
    assert resp.status_code == 302 and WorkerProfile.query.count() == 1


def test_page_shows_counts_rows_and_no_profile_content(admin, make_profile, make_take, review):
    p = make_profile("+14155550187", name="John O'Connor", onboarding_state="completed",
                     profile_data={"work_experience": [{"title": "SECRET-JOB"}],
                                   "availability": "SECRET-AVAIL", "summary": "SECRET-JOB"},
                     transcripts={"story": "SECRET-TRANSCRIPT"})
    review(p, content="SECRET-REVIEW")
    make_take(p, transcript="SECRET-TRANSCRIPT")
    html = admin.get("/admin/profiles").get_data(as_text=True)
    assert "John O&#39;Connor" in html and "+14155550187" in html and "completed" in html
    assert "Total" in html and "With reviews" in html
    assert "/admin/recordings?phone=%2B14155550187" in html
    assert f"/admin/profiles/{p.id}/delete" in html
    for secret in SECRETS:
        assert secret not in html


def test_page_timezone_label_and_local_times(app, admin, make_profile):
    app.config["ADMIN_TIMEZONE"] = "America/Los_Angeles"
    make_profile(created_at=datetime(2026, 10, 17, 3, 0), updated_at=datetime(2026, 10, 17, 3, 5))
    html = admin.get("/admin/profiles").get_data(as_text=True)
    assert "Timezone: America/Los Angeles" in html
    assert "2026-10-16 20:00" in html and "2026-10-16 20:05" in html  # SQLite naive = UTC


def test_page_shows_current_time_in_admin_zone(app, admin):
    app.config["ADMIN_TIMEZONE"] = "America/Los_Angeles"
    pacific = ZoneInfo("America/Los_Angeles")
    before = datetime.now(pacific).strftime("%Y-%m-%d %H:%M")
    html = admin.get("/admin/profiles").get_data(as_text=True)
    after = datetime.now(pacific).strftime("%Y-%m-%d %H:%M")
    assert f"now {before}" in html or f"now {after}" in html


def test_page_incomplete_status_and_filters(admin, population):
    html = admin.get("/admin/profiles", query_string={"status": "incomplete"}).get_data(as_text=True)
    assert "stopped at" in html and "Done 0" not in html and "extraction error" in html
    assert '<option value="incomplete" selected' in html
    html = admin.get("/admin/profiles", query_string={"q": "0201"}).get_data(as_text=True)
    assert "Nina" in html and "Maria" not in html
    html = admin.get("/admin/profiles?status=bogus").get_data(as_text=True)
    assert "Unknown status" in html


@pytest.mark.parametrize("qs", ["page=999", "page=abc", "page=-3", "page=1e20",
                                "page=99999999999999999999", "endpoint=x", "_external=1"])
def test_odd_query_strings_do_not_error(admin, make_profile, qs):
    make_profile()
    assert admin.get(f"/admin/profiles?{qs}").status_code == 200


def test_paging(admin, make_profile):
    for i in range(51):
        make_profile(f"+1415555{i:04d}", name=f"W{i:02d}")
    page1 = admin.get("/admin/profiles").get_data(as_text=True)
    assert "W50" in page1 and "W00" not in page1 and "Older" in page1
    page2 = admin.get("/admin/profiles?page=2").get_data(as_text=True)
    assert "W00" in page2 and "Newer" in page2


def test_dashboard_links_to_profiles(admin):
    assert "/admin/profiles" in admin.get("/admin/").get_data(as_text=True)


# --- delete ------------------------------------------------------------------

def test_delete_confirmation_page_lists_footprint(admin, make_profile, make_take, review):
    p = make_profile("+14155550187", name="John", onboarding_state="story",
                     transcripts={"story": "SECRET-TRANSCRIPT"})
    make_take(p, audio=b"x" * 2048)
    review(p, content="SECRET-REVIEW")
    html = admin.get(f"/admin/profiles/{p.id}/delete").get_data(as_text=True)
    assert "John" in html and "1 review" in html and "1 voice recording" in html
    assert "last 4 digits" in html and "within 14 days" in html
    for secret in SECRETS:
        assert secret not in html


def test_delete_wrong_code_keeps_everything(admin, make_profile, make_take):
    p = make_profile("+14155550187")
    make_take(p)
    for code in ("", "1234", "0188"):
        resp = admin.post(f"/admin/profiles/{p.id}/delete", data={"confirm": code})
        assert resp.status_code == 400 and "Nothing was deleted" in resp.get_data(as_text=True)
    assert WorkerProfile.query.count() == 1 and VoiceRecording.query.count() == 1


def test_delete_success(admin, make_profile, make_take, review, caplog):
    p = make_profile("+14155550187", name="John O'Connor")
    other = make_profile("+14155550199", name="Keep Me")
    make_take(p)
    review(p)
    pid, other_id = p.id, other.id
    with caplog.at_level(logging.INFO):
        resp = admin.post(f"/admin/profiles/{pid}/delete", data={"confirm": " 0187 "})
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/admin/profiles")
    assert db.session.get(WorkerProfile, pid) is None and db.session.get(WorkerProfile, other_id) is not None
    assert VoiceRecording.query.count() == 0 and Review.query.count() == 0
    logged = caplog.text
    assert f"deleted profile {pid}" in logged
    assert "0187" not in logged and "O'Connor" not in logged
    html = admin.get("/admin/profiles").get_data(as_text=True)
    assert f"Deleted profile {pid}" in html and "Keep Me" in html


def test_delete_profile_without_phone_uses_id(admin, make_profile):
    p = make_profile(phone=None)
    pid = p.id
    html = admin.get(f"/admin/profiles/{pid}/delete").get_data(as_text=True)
    assert "profile ID" in html
    assert admin.post(f"/admin/profiles/{pid}/delete", data={"confirm": str(pid)}).status_code == 302
    assert db.session.get(WorkerProfile, pid) is None


def test_delete_unknown_profile_404(admin):
    assert admin.get("/admin/profiles/99999/delete").status_code == 404
    assert admin.post("/admin/profiles/99999/delete", data={"confirm": "99999"}).status_code == 404
