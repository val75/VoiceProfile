import logging
from unittest.mock import patch

from authlib.integrations.flask_client import OAuthError

from models.admin import AdminIdentity

GOOG = "https://accounts.google.com"


def _token(email, verified=True, sub="sub-1"):
    return {"userinfo": {"iss": GOOG, "sub": sub, "email": email, "email_verified": verified}}


def test_auth_callback_grants_break_glass_admin(client):
    with patch("blueprints.admin.routes.oauth.admin_idp.authorize_access_token",
               return_value=_token("founder@example.com")):
        resp = client.get("/admin/auth", follow_redirects=False)
    assert resp.status_code == 302
    assert "/admin" in resp.headers["Location"]
    with client.session_transaction() as sess:
        assert isinstance(sess["admin"], int)
    assert AdminIdentity.query.filter_by(issuer=GOOG, subject="sub-1").count() == 1


def test_auth_callback_rejects_stranger(client):
    with patch("blueprints.admin.routes.oauth.admin_idp.authorize_access_token",
               return_value=_token("stranger@example.com")):
        resp = client.get("/admin/auth", follow_redirects=False)
    assert resp.status_code == 403
    with client.session_transaction() as sess:
        assert "admin" not in sess


def test_auth_callback_rejects_unverified(client):
    with patch("blueprints.admin.routes.oauth.admin_idp.authorize_access_token",
               return_value=_token("founder@example.com", verified=False)):
        resp = client.get("/admin/auth", follow_redirects=False)
    assert resp.status_code == 403
    with client.session_transaction() as sess:
        assert "admin" not in sess


def test_auth_callback_string_false_email_verified_denied(client):
    # Some non-Google IdPs send the claim as a string; "false" is truthy.
    with patch("blueprints.admin.routes.oauth.admin_idp.authorize_access_token",
               return_value=_token("founder@example.com", verified="false")):
        resp = client.get("/admin/auth", follow_redirects=False)
    assert resp.status_code == 403
    with client.session_transaction() as sess:
        assert "admin" not in sess


def test_auth_callback_oauth_error_is_403(client):
    # Consent cancelled / state mismatch / expired code → 403, never a 500.
    with patch("blueprints.admin.routes.oauth.admin_idp.authorize_access_token",
               side_effect=OAuthError(error="access_denied")):
        resp = client.get("/admin/auth", follow_redirects=False)
    assert resp.status_code == 403
    with client.session_transaction() as sess:
        assert "admin" not in sess


def test_auth_callback_success_reaches_dashboard(client):
    with patch("blueprints.admin.routes.oauth.admin_idp.authorize_access_token",
               return_value=_token("founder@example.com")):
        client.get("/admin/auth", follow_redirects=False)
    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert b"founder@example.com" in resp.data


def test_auth_callback_logs_denial(client, caplog):
    with patch("blueprints.admin.routes.oauth.admin_idp.authorize_access_token",
               return_value=_token("stranger@example.com")):
        with caplog.at_level(logging.WARNING):
            client.get("/admin/auth", follow_redirects=False)
    assert any(
        r.levelno == logging.WARNING and "Admin login denied" in r.getMessage()
        for r in caplog.records
    )
