import re

import pytest

from models.review import Review


@pytest.fixture
def profile(make_profile):
    return make_profile(onboarding_state="completed")


def _checked_stars(html):
    return re.findall(r'id="star(\d)"[^>]*\bchecked\b', html)


def test_missing_rating_keeps_what_the_reviewer_entered(client, profile):
    resp = client.post(f"/p/{profile.id}/review/new", data={
        "reviewer_name": "Maria",
        "content": "Great painter",
        "transcript": "great painter",
    })
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "Please select a rating." in html
    assert 'value="Maria"' in html
    assert ">Great painter</textarea>" in html
    assert 'name="transcript" value="great painter"' in html
    assert Review.query.count() == 0


def test_missing_text_keeps_the_rating_and_name(client, profile):
    resp = client.post(f"/p/{profile.id}/review/new", data={
        "reviewer_name": "Maria",
        "rating": "4",
        "content": "   ",
    })
    html = resp.get_data(as_text=True)

    assert "Please write something in your review." in html
    assert 'value="Maria"' in html
    assert _checked_stars(html) == ["4"]
    assert Review.query.count() == 0


def test_kept_values_are_escaped(client, profile):
    resp = client.post(f"/p/{profile.id}/review/new", data={
        "reviewer_name": '"><script>alert(1)</script>',
        "content": "</textarea><script>alert(2)</script>",
    })
    html = resp.get_data(as_text=True)

    assert "<script>alert(1)" not in html
    assert "<script>alert(2)" not in html


def test_out_of_range_rating_selects_no_star(client, profile):
    resp = client.post(f"/p/{profile.id}/review/new", data={"rating": "9", "content": "Great"})
    html = resp.get_data(as_text=True)

    assert "Please select a rating." in html
    assert _checked_stars(html) == []


def test_new_form_starts_empty(client, profile):
    html = client.get(f"/p/{profile.id}/review/new").get_data(as_text=True)

    assert _checked_stars(html) == []
    assert 'name="transcript" value=""' in html


def test_review_page_uses_the_one_button_recorder(client, profile):
    html = client.get(f"/p/{profile.id}/review/new").get_data(as_text=True)

    assert html.count('id="recordBtn"') == 1
    assert 'id="voiceStop"' not in html and 'id="voiceSend"' not in html
    assert "onboarding/js/voiceRecorder.js" in html
    assert "onboarding/css/recordButton.css" in html
