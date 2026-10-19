import pytest

from blueprints.onboarding.routes import RECORD_PROMPTS


@pytest.fixture
def worker(client, make_profile):
    p = make_profile()
    with client.session_transaction() as sess:
        sess["profile_id"] = p.id
    return p


@pytest.mark.parametrize("step", ["name", "story", "availability"])
def test_question_page_has_one_record_button_and_its_prompt(client, worker, step):
    resp = client.get(f"/onboarding/{worker.id}/{step}")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert html.count('id="recordBtn"') == 1
    assert 'id="stop"' not in html and 'id="send"' not in html
    assert RECORD_PROMPTS[step] in html


@pytest.mark.parametrize("step, has_building", [
    ("name", False), ("story", False), ("availability", True),
])
def test_building_circle_only_on_last_step_and_hidden(client, worker, step, has_building):
    html = client.get(f"/onboarding/{worker.id}/{step}").get_data(as_text=True)

    assert ('id="building"' in html) == has_building
    if has_building:
        tag = html[html.index('id="building"'):].split(">", 1)[0]
        assert "hidden" in tag
        assert "Building your profile…" in html


def test_edit_button_is_not_hidden_on_load(client, worker):
    html = client.get(f"/onboarding/{worker.id}/story").get_data(as_text=True)
    edit_tag = html[html.index('id="btnEdit"'):].split(">", 1)[0]
    assert "hidden" not in edit_tag and "display:none" not in edit_tag
