import logging
from datetime import datetime, timezone

import pytest

from tests.test_webm_duration import WEBM, _duration

UTC = timezone.utc


@pytest.fixture
def admin(client):
    client.get("/admin/login")  # dev fallback: debug + loopback
    return client


def test_requires_admin(client, make_profile, make_take):
    t = make_take(make_profile())
    for url in ("/admin/recordings", f"/admin/recordings/{t.id}/audio"):
        resp = client.get(url)
        assert resp.status_code == 302 and "/admin/login" in resp.headers["Location"]


def test_worker_session_cannot_get_in(client, make_profile, make_take):
    p = make_profile()
    t = make_take(p)
    with client.session_transaction() as sess:
        sess["profile_id"] = p.id
    assert client.get("/admin/recordings").status_code == 302
    assert client.get(f"/admin/recordings/{t.id}/audio").status_code == 302


def test_feed_lists_takes(admin, make_profile, make_take):
    p = make_profile(name="Ana")
    make_take(p, transcript="I cleaned houses", edited_text="I cleaned houses for 5 years",
              duration_ms=61000, accepted=True)
    html = admin.get("/admin/recordings").get_data(as_text=True)
    assert "+14155550100" in html and "Ana" in html
    assert "I cleaned houses for 5 years" in html and "accepted" in html
    assert 'preload="none"' in html
    assert "Timezone: UTC" in html


def test_phone_filter_and_invalid_phone(admin, make_profile, make_take):
    make_take(make_profile("+14155550100"), transcript="mine")
    make_take(make_profile("+14155550199"), transcript="theirs")
    html = admin.get("/admin/recordings",
                     query_string={"phone": "(415) 555-0100"}).get_data(as_text=True)
    assert "mine" in html and "theirs" not in html
    html = admin.get("/admin/recordings", query_string={"phone": "12"}).get_data(as_text=True)
    assert "Not a valid phone number" in html and "mine" not in html


def test_times_shown_in_admin_timezone(app, admin, make_profile, make_take):
    app.config["ADMIN_TIMEZONE"] = "America/Los_Angeles"
    make_take(make_profile(), created_at=datetime(2026, 10, 15, 3, 0, tzinfo=UTC))
    html = admin.get("/admin/recordings?from=2026-10-14&to=2026-10-14").get_data(as_text=True)
    assert "2026-10-14 20:00" in html and "Timezone: America/Los Angeles" in html


def test_paging(admin, make_profile, make_take):
    p = make_profile()
    for i in range(1, 52):
        make_take(p, attempt=i, transcript=f"take-{i:02d}")
    page1 = admin.get("/admin/recordings").get_data(as_text=True)
    assert "take-51" in page1 and "take-01" not in page1 and "Older" in page1
    page2 = admin.get("/admin/recordings?page=2").get_data(as_text=True)
    assert "take-01" in page2 and "Newer" in page2


@pytest.mark.parametrize("page", ["999", "abc", "-3"])
def test_odd_page_numbers_do_not_error(admin, make_profile, make_take, page):  # Review Focus 2
    make_take(make_profile())
    assert admin.get(f"/admin/recordings?page={page}").status_code == 200


def test_untrusted_text_is_escaped(admin, make_profile, make_take):  # Review Focus 1
    make_take(make_profile(name="<b>Eve</b>"), transcript="<script>alert(1)</script>",
              stt_error="<img src=x>", edited_text="<i>x</i>")
    html = admin.get("/admin/recordings").get_data(as_text=True)
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html
    assert "<b>Eve</b>" not in html and "<img src=x>" not in html and "<i>x</i>" not in html


def test_profile_without_phone_lists(admin, make_profile, make_take):  # Review Focus 3
    make_take(make_profile(phone=None), transcript="no phone yet")
    assert "no phone yet" in admin.get("/admin/recordings").get_data(as_text=True)


def test_audio_endpoint(admin, make_profile, make_take, caplog):
    t = make_take(make_profile(), audio=b"0123456789", mime_type="audio/mp4")
    with caplog.at_level(logging.INFO):
        resp = admin.get(f"/admin/recordings/{t.id}/audio")
    assert resp.status_code == 200 and resp.data == b"0123456789"
    assert resp.mimetype == "audio/mp4"
    assert resp.headers["Cache-Control"] == "no-store"
    assert any(f"played recording {t.id}" in r.getMessage() for r in caplog.records)
    part = admin.get(f"/admin/recordings/{t.id}/audio", headers={"Range": "bytes=2-4"})
    assert part.status_code == 206 and part.data == b"234"
    assert admin.get("/admin/recordings/99999/audio").status_code == 404


def test_dashboard_links_to_recordings(admin):
    assert "/admin/recordings" in admin.get("/admin/").get_data(as_text=True)


def test_non_audio_mime_is_not_served_as_is(admin, make_profile, make_take):
    t = make_take(make_profile(), audio=b"<script>alert(1)</script>", mime_type="text/html")
    resp = admin.get(f"/admin/recordings/{t.id}/audio")
    assert resp.mimetype == "application/octet-stream"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in resp.headers["Content-Security-Policy"]


def test_audio_mime_params_dropped(admin, make_profile, make_take):
    t = make_take(make_profile(), mime_type="audio/webm;codecs=opus")
    assert admin.get(f"/admin/recordings/{t.id}/audio").mimetype == "audio/webm"


@pytest.mark.parametrize("rng, logged", [("bytes=0-1", True), ("bytes=0-", True),
                                         ("bytes=4-", False)])
def test_playback_logged_once_per_play_incl_safari(admin, make_profile, make_take, caplog,
                                                   rng, logged):
    t = make_take(make_profile(), audio=b"0123456789")
    with caplog.at_level(logging.INFO):
        admin.get(f"/admin/recordings/{t.id}/audio", headers={"Range": rng})
    assert any(f"played recording {t.id}" in r.getMessage() for r in caplog.records) is logged


def test_webm_served_with_duration_filled_in(admin, make_profile, make_take):
    t = make_take(make_profile(), audio=WEBM, mime_type="audio/webm;codecs=opus",
                  duration_ms=10416)
    full = admin.get(f"/admin/recordings/{t.id}/audio").data
    assert _duration(full) == 10416.0 and len(full) == len(WEBM)
    part = admin.get(f"/admin/recordings/{t.id}/audio", headers={"Range": "bytes=80-99"})
    assert part.status_code == 206 and part.data == full[80:100]


def test_decision_filter(admin, make_profile, make_take):
    p = make_profile()
    make_take(p, attempt=1, transcript="said-yes", accepted=True)
    make_take(p, attempt=2, transcript="said-no", accepted=False)
    make_take(p, attempt=3, transcript="no-answer")
    for decision, shown in (("accepted", "said-yes"), ("re-recorded", "said-no"),
                            ("undecided", "no-answer")):
        html = admin.get("/admin/recordings",
                         query_string={"decision": decision}).get_data(as_text=True)
        assert shown in html
        assert sum(t in html for t in ("said-yes", "said-no", "no-answer")) == 1
        assert f'<option value="{decision}" selected' in html
    html = admin.get("/admin/recordings?decision=maybe").get_data(as_text=True)
    assert "Unknown decision" in html
