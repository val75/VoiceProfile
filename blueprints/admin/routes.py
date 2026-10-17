import io

from authlib.integrations.flask_client import OAuthError
from flask import (
    abort, session, redirect, url_for, render_template, current_app, request, send_file,
)

from extensions.database import db
from extensions.oauth import oauth
from models.recording import VoiceRecording
from . import admin_bp
from .decorators import DEV_ADMIN, admin_required, current_admin
from services.admin_service import resolve_admin
from services.recording_service import DECISIONS, FilterError, build_filters, search_takes
from services.timezones import admin_zone, to_admin_local
from services.webm import with_duration

_LOOPBACK = ("127.0.0.1", "::1")
PAGE_SIZE = 50

# Types an <audio> element plays. The stored type comes from the worker's upload,
# so anything else is served as opaque bytes and can never render on this origin.
_AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav",
                "audio/x-wav", "audio/aac"}


def _safe_audio_type(mime_type):
    base = (mime_type or "").split(";")[0].strip().lower()
    return base if base in _AUDIO_TYPES else "application/octet-stream"


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


@admin_bp.route("/recordings")
@admin_required
def recordings():
    """Search / browse raw voice takes; no filters = newest-first feed."""
    args = request.args
    error, page = None, None
    try:
        filters = build_filters(args.get("phone"), args.get("from"), args.get("to"),
                                args.get("step"), args.get("decision"))
    except FilterError as e:
        error = str(e)
    else:
        page_num = max(args.get("page", 1, type=int), 1)
        page = search_takes(**filters).paginate(page=page_num, per_page=PAGE_SIZE,
                                                error_out=False)
    base_args = {k: v for k, v in args.items() if k != "page" and v}
    return render_template(
        "admin/recordings.html",
        page=page, error=error, args=args, base_args=base_args,
        to_local=to_admin_local, zone_name=str(admin_zone()), decisions=DECISIONS,
    )


@admin_bp.route("/recordings/<int:take_id>/audio")
@admin_required
def recording_audio(take_id):
    """Stream one take's raw audio (Range-capable so the player can seek)."""
    take = db.session.get(VoiceRecording, take_id)
    if take is None:
        abort(404)
    # Log the start of a playback (Chrome's bytes=0-, Safari's bytes=0-1 probe),
    # not every seek request.
    rng = request.range
    if rng is None or rng.ranges[0][0] == 0:
        admin = current_admin()
        current_app.logger.info("Admin %s played recording %s",
                                admin.id if admin else DEV_ADMIN, take.id)
    audio = with_duration(take.audio, take.duration_ms)  # else the seek bar jumps to the end
    resp = send_file(io.BytesIO(audio), mimetype=_safe_audio_type(take.mime_type),
                     conditional=True, max_age=0)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = "sandbox"
    return resp
