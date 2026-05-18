# app/blueprints/profiles/routes.py

import io

from flask import Blueprint, request, jsonify, render_template, url_for, send_file
from extensions.database import db
from models.profile import WorkerProfile
from models.review import Review
from blueprints.auth.decorators import profile_owner_required

profiles_bp = Blueprint("profiles", __name__, template_folder="templates", static_folder="static")


@profiles_bp.route("/", methods=["POST"])
def create_profile():
    data = request.get_json()
    profile = WorkerProfile(**data)
    db.session.add(profile)
    db.session.commit()
    return jsonify({"id": profile.id}), 201


@profiles_bp.route("/<int:profile_id>", methods=["GET"])
def get_profile(profile_id):
    profile = WorkerProfile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    return jsonify({
        "id": profile.id,
        "name": profile.name,
        "profile_data": profile.profile_data
    })


@profiles_bp.route("/<int:profile_id>/view", methods=["GET"])
@profile_owner_required
def view_profile(profile_id):
    profile = WorkerProfile.query.get_or_404(profile_id)
    edit_url = url_for("onboarding.review_step", profile_id=profile.id)
    reviews = Review.query.filter_by(profile_id=profile_id).order_by(Review.created_at.desc()).all()
    return render_template("profiles/view.html", profile=profile, edit_url=edit_url, reviews=reviews)


@profiles_bp.route("/<int:profile_id>/qr.png")
@profile_owner_required
def qr_code(profile_id):
    import qrcode
    public_url = request.host_url.rstrip("/") + url_for("reviews.public_profile", profile_id=profile_id)
    img = qrcode.make(public_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@profiles_bp.route("/", methods=["GET"])
def list_profiles():
    profiles = WorkerProfile.query.all()
    result = []
    for p in profiles:
        result.append({
            "id": p.id,
            "name": p.name,
            "profile_data": p.profile_data
        })
    return jsonify(result)

