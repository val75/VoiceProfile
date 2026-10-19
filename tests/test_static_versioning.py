import hashlib
import os
import re

from flask import url_for

from extensions.static_versioning import file_version

ONBOARDING_STATIC = os.path.join(
    os.path.dirname(__file__), "..", "blueprints", "onboarding", "static"
)


def _content_hash(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:10]


def test_static_links_carry_content_hash(app):
    path = os.path.join(ONBOARDING_STATIC, "onboarding", "js", "confirmHandler.js")
    with app.test_request_context():
        url = url_for("onboarding.static", filename="onboarding/js/confirmHandler.js")
    assert url == f"/onboarding/static/onboarding/js/confirmHandler.js?v={_content_hash(path)}"


def test_question_page_scripts_and_styles_are_versioned(client, make_profile):
    p = make_profile()
    with client.session_transaction() as sess:
        sess["profile_id"] = p.id
    html = client.get(f"/onboarding/{p.id}/story").get_data(as_text=True)

    links = re.findall(r'(?:src|href)="(/onboarding/static/[^"]+)"', html)
    assert links
    assert all(re.search(r"\?v=[0-9a-f]{10}$", link) for link in links)


def test_version_changes_with_content(tmp_path):
    f = tmp_path / "app.js"
    f.write_text("one")
    first = file_version(str(tmp_path), "app.js")
    f.write_text("two!")
    assert file_version(str(tmp_path), "app.js") != first


def test_missing_file_gets_no_version(app):
    with app.test_request_context():
        url = url_for("onboarding.static", filename="onboarding/js/nope.js")
    assert url == "/onboarding/static/onboarding/js/nope.js"


def test_path_outside_static_folder_gets_no_version(tmp_path):
    (tmp_path / "secret.txt").write_text("x")
    static = tmp_path / "static"
    static.mkdir()
    assert file_version(str(static), "../secret.txt") is None


def test_versioned_url_still_serves_the_file(client):
    with client.get("/onboarding/static/onboarding/js/confirmHandler.js?v=anything") as resp:
        assert resp.status_code == 200
        assert b"Save and continue" in resp.data
