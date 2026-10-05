from authlib.integrations.flask_client import OAuthError
from flask import session, redirect, url_for, render_template, current_app, request

from extensions.oauth import oauth
from . import admin_bp
from .decorators import DEV_ADMIN, admin_required, current_admin
from services.admin_service import resolve_admin

_LOOPBACK = ("127.0.0.1", "::1")


@admin_bp.route("/login")
def login():
    # Offline dev fallback: debug mode AND a loopback client only. Behind the
    # Cloudflare Tunnel, ProxyFix sets remote_addr to the real client IP, so
    # this can never fire for internet traffic even if FLASK_DEBUG is flipped.
    if current_app.debug and request.remote_addr in _LOOPBACK:
        session["admin"] = DEV_ADMIN
        return redirect(url_for("admin.dashboard"))
    redirect_uri = url_for("admin.auth", _external=True)
    return oauth.admin_idp.authorize_redirect(redirect_uri)


@admin_bp.route("/auth")
def auth():
    try:
        token = oauth.admin_idp.authorize_access_token()
    except OAuthError as e:
        current_app.logger.warning("Admin login failed at OIDC callback: %s", e.error)
        return render_template("admin/not_authorized.html"), 403
    info = token.get("userinfo") or {}
    admin = resolve_admin(
        issuer=info.get("iss"),
        subject=info.get("sub"),
        email=info.get("email"),
        email_verified=info.get("email_verified") is True,
        name=info.get("name"),
    )
    if admin is None:
        current_app.logger.warning(
            "Admin login denied: email=%s email_verified=%r iss=%s sub=%s",
            info.get("email"), info.get("email_verified"), info.get("iss"), info.get("sub"),
        )
        return render_template("admin/not_authorized.html"), 403
    session["admin"] = admin.id
    current_app.logger.info(
        "Admin login: id=%s email=%s iss=%s sub=%s",
        admin.id, admin.email, info.get("iss"), info.get("sub"),
    )
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/logout", methods=["POST"])
def logout():
    session.pop("admin", None)
    return redirect(url_for("admin.login"))


@admin_bp.route("/")
@admin_required
def dashboard():
    return render_template("admin/dashboard.html", admin=current_admin())
