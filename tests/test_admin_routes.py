from unittest.mock import patch

from extensions.database import db
from models.admin import AdminUser
from services.admin_service import add_admin, disable_admin

_REDIRECT = "blueprints.admin.routes.oauth.admin_idp.authorize_redirect"
_GOOGLE_302 = ("", 302, {"Location": "https://accounts.google.com/o/oauth2/v2/auth"})


def _login_as(client, admin_id):
    with client.session_transaction() as sess:
        sess["admin"] = admin_id


def test_dashboard_requires_admin(client):
    resp = client.get("/admin/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/admin/login" in resp.headers["Location"]


def test_dev_fallback_login_grants_admin(client):
    # app fixture runs with FLASK_DEBUG=1 → dev fallback active.
    resp = client.get("/admin/login", follow_redirects=False)
    assert resp.status_code == 302
    assert "/admin" in resp.headers["Location"]
    with client.session_transaction() as sess:
        assert sess["admin"] == "dev"
    assert client.get("/admin/").status_code == 200


def test_logout_clears_admin(client):
    client.get("/admin/login")  # dev login
    resp = client.post("/admin/logout", follow_redirects=False)
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert "admin" not in sess


# --- I2: dev fallback is debug AND loopback only --------------------------

def test_dev_login_requires_loopback(client):
    with patch(_REDIRECT, return_value=_GOOGLE_302) as redirect:
        client.get("/admin/login", environ_base={"REMOTE_ADDR": "203.0.113.5"})
    redirect.assert_called_once()
    with client.session_transaction() as sess:
        assert "admin" not in sess


def test_dev_login_not_granted_through_proxy(client):
    # Loopback socket (cloudflared), but ProxyFix rewrites remote_addr to the
    # real client from X-Forwarded-For — the Cloudflare Tunnel case.
    with patch(_REDIRECT, return_value=_GOOGLE_302) as redirect:
        client.get("/admin/login", headers={"X-Forwarded-For": "203.0.113.5"})
    redirect.assert_called_once()
    with client.session_transaction() as sess:
        assert "admin" not in sess


def test_prod_login_redirects_to_google_with_https_uri(app, client):
    app.config["DEBUG"] = False
    with patch(_REDIRECT, return_value=_GOOGLE_302) as redirect:
        resp = client.get("/admin/login", headers={
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "voiceprofile.example",
            "X-Forwarded-For": "203.0.113.5",
        })
    assert resp.status_code == 302
    redirect.assert_called_once_with("https://voiceprofile.example/admin/auth")


# --- I1: the admin row is re-checked on every request ----------------------

def test_dev_session_rejected_when_debug_off(app, client):
    _login_as(client, "dev")
    app.config["DEBUG"] = False
    resp = client.get("/admin/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/admin/login" in resp.headers["Location"]
    with client.session_transaction() as sess:
        assert "admin" not in sess


def test_real_admin_session_shows_dashboard(client):
    admin = add_admin("ops@example.com")
    _login_as(client, admin.id)
    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert b"ops@example.com" in resp.data


def test_disabled_admin_session_revoked(client):
    admin = add_admin("ops@example.com")
    _login_as(client, admin.id)
    assert client.get("/admin/").status_code == 200
    disable_admin("ops@example.com")
    resp = client.get("/admin/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/admin/login" in resp.headers["Location"]
    with client.session_transaction() as sess:
        assert "admin" not in sess


def test_deleted_admin_session_revoked(client):
    admin = add_admin("ops@example.com")
    _login_as(client, admin.id)
    db.session.delete(admin)
    db.session.commit()
    assert AdminUser.query.count() == 0
    resp = client.get("/admin/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/admin/login" in resp.headers["Location"]
    with client.session_transaction() as sess:
        assert "admin" not in sess
