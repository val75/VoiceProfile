# app/blueprints/profiles/routes.py

from flask import Blueprint, request, jsonify
from extensions.database import db
from models.profile import Profile

profiles_bp = Blueprint("profiles", __name__)


@profiles_bp.route("/", methods=["POST"])
def create_profile():
    data = request.get_json()
    profile = Profile(**data)
    db.session.add(profile)
    db.session.commit()
    return jsonify({"id": profile.id}), 201


@profiles_bp.route("/<int:profile_id>", methods=["GET"])
def get_profile(profile_id):
    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    return jsonify({
        "id": profile.id,
        "name": profile.name,
        "profile_data": profile.profile_data
    })


@profiles_bp.route("/", methods=["GET"])
def list_profiles():
    profiles = Profile.query.all()
    result = []
    for p in profiles:
        result.append({
            "id": p.id,
            "name": p.name,
            "profile_data": p.profile_data
        })
    return jsonify(result)

