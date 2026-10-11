from app import create_app
from config import _parse_admin_url_prefix


def test_parse_admin_url_prefix_default():
    assert _parse_admin_url_prefix(None) == "/admin"
    assert _parse_admin_url_prefix("") == "/admin"
    assert _parse_admin_url_prefix(" / ") == "/admin"


def test_parse_admin_url_prefix_normalizes_slashes():
    assert _parse_admin_url_prefix("yoda") == "/yoda"
    assert _parse_admin_url_prefix("/yoda/") == "/yoda"
    assert _parse_admin_url_prefix(" /ops/yoda ") == "/ops/yoda"


def _client(prefix):
    app = create_app(test_config={"TESTING": True, "DEBUG": True, "ADMIN_URL_PREFIX": prefix})
    return app.test_client()


def test_admin_mounted_under_custom_prefix():
    client = _client("/yoda")
    resp = client.get("/yoda/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/yoda/login")

    # dev fallback (debug + loopback) lands back on the custom dashboard
    resp = client.get("/yoda/login", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/yoda/")


def test_default_admin_path_gone_under_custom_prefix():
    client = _client("/yoda")
    assert client.get("/admin/").status_code == 404
    assert client.get("/admin/login").status_code == 404
