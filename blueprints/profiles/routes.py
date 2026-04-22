# app/blueprints/profiles/routes.py

from flask import Blueprint, request, jsonify, render_template, url_for
from extensions.database import db
from models.profile import WorkerProfile

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
def view_profile(profile_id):
    profile = WorkerProfile.query.get_or_404(profile_id)
    edit_url = url_for("onboarding.review_step", profile_id=profile.id)
    return render_template("profiles/view.html", profile=profile, edit_url=edit_url)


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

