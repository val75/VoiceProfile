import logging

from flask import render_template, request, redirect, url_for, session, flash, current_app

from . import auth_bp
from models.profile import WorkerProfile
from extensions.database import db
from services.otp_service import send_code, verify_code, OTPError

logger = logging.getLogger(__name__)


def _post_auth_url(profile) -> str:
    """Return the URL the user should land on after a successful login."""
    state = profile.onboarding_state or "name"
    if state == "completed":
        return url_for("profiles.view_profile", profile_id=profile.id)
    if state in ("name", "name_confirm"):
        return url_for("onboarding.name_step", profile_id=profile.id)
    if state in ("skills", "experience", "availability"):
        return url_for("onboarding.voice_step", profile_id=profile.id, step=state)
    if state == "review":
        return url_for("onboarding.review_step", profile_id=profile.id)
    return url_for("onboarding.name_step", profile_id=profile.id)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        if not phone:
            flash("Please enter your phone number.")
            return render_template("auth/login.html")

        try:
            code = send_code(phone)
        except OTPError as e:
            logger.error("send_code failed for %s: %s", phone, e)
            flash("Could not send a code. Please try again.")
            return render_template("auth/login.html")

        session["pending_phone"] = phone
        if current_app.debug:
            session["debug_code"] = code
        return redirect(url_for("auth.verify"))

    return render_template("auth/login.html")


@auth_bp.route("/verify", methods=["GET", "POST"])
def verify():
    phone = session.get("pending_phone")
    if not phone:
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        code = request.form.get("code", "").strip()
        if not verify_code(phone, code):
            flash("Invalid or expired code. Please try again.")
            return render_template("auth/verify.html", phone=phone, debug_code=None)

        # Code is valid — look up or create the profile for this phone.
        profile = WorkerProfile.query.filter_by(phone_number=phone).first()
        if not profile:
            profile = WorkerProfile(phone_number=phone)
            db.session.add(profile)
            db.session.commit()

        session.pop("pending_phone", None)
        session["profile_id"] = profile.id

        return redirect(_post_auth_url(profile))

    debug_code = session.pop("debug_code", None)
    return render_template("auth/verify.html", phone=phone, debug_code=debug_code)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
