# app/blueprints/profile_builder/routes.py

from flask import Blueprint, request, jsonify
from services.nlp_service import extract_profile_data

profile_builder_bp = Blueprint("profile_builder", __name__)


@profile_builder_bp.route("/parse", methods=["POST"])
def parse_text():
    data = request.get_json()
    text = data.get("text")
    if not text:
        return jsonify({"error": "Missing text"}), 400

    structured = extract_profile_data(text)
    return jsonify(structured)
