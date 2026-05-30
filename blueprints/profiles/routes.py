# app/blueprints/profiles/routes.py

import io
import logging

from flask import Blueprint, request, jsonify, render_template, url_for, send_file, Response
from PIL import Image, ImageOps
from extensions.database import db
from models.profile import WorkerProfile
from models.review import Review
from blueprints.auth.decorators import profile_owner_required

logger = logging.getLogger(__name__)

profiles_bp = Blueprint("profiles", __name__, template_folder="templates", static_folder="static")

AVATAR_SIZE = 512
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # reject obviously oversized uploads


def _process_avatar(file_storage) -> bytes:
    """Normalize an uploaded image into a square, EXIF-corrected JPEG."""
    img = Image.open(file_storage.stream)
    img = ImageOps.exif_transpose(img)                       # honor camera orientation
    img = img.convert("RGB")                                 # drop alpha/palette for JPEG
    img = ImageOps.fit(img, (AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)  # center-crop + resize
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue()


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


@profiles_bp.route("/<int:profile_id>/photo", methods=["GET"])
def photo(profile_id):
    """Serve the profile photo. Public so visitors can see it on the public page."""
    profile = WorkerProfile.query.get_or_404(profile_id)
    if not profile.photo:
        return "", 404
    resp = Response(profile.photo, mimetype=profile.photo_mime or "image/jpeg")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@profiles_bp.route("/<int:profile_id>/photo", methods=["POST"])
@profile_owner_required
def upload_photo(profile_id):
    """Accept an image upload, normalize it, and store it on the profile."""
    profile = WorkerProfile.query.get_or_404(profile_id)

    if request.content_length and request.content_length > MAX_UPLOAD_BYTES:
        return jsonify({"error": "Image is too large."}), 413

    file = request.files.get("photo")
    if not file or not file.filename:
        return jsonify({"error": "No image provided."}), 400

    try:
        data = _process_avatar(file)
    except Exception:
        logger.exception("Photo processing failed for profile %s", profile_id)
        return jsonify({"error": "Could not process that image. Please try a different photo."}), 400

    profile.photo = data
    profile.photo_mime = "image/jpeg"
    db.session.commit()

    return jsonify({"success": True, "photo_url": url_for("profiles.photo", profile_id=profile.id)})


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

