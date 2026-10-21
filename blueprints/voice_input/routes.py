# app/blueprints/voice_input/routes.py

from flask import Blueprint, request, jsonify, current_app
from werkzeug.exceptions import RequestEntityTooLarge
from services.stt_service import transcribe_audio, SpeechToTextError
from services.rate_limit import check_transcribe_rate_limit

voice_input_bp = Blueprint("voice_input", __name__, url_prefix="/voice")


@voice_input_bp.route("/transcribe", methods=["POST"])
def transcribe():
    """Public speech-to-text for anonymous voice reviews on /p/<id>.

    No login (reviewers have none), so it is rate-limited per IP and size-capped.
    request.remote_addr is the real client IP thanks to ProxyFix.
    """
    # Count every call, oversized ones included, before reading the body.
    reason = check_transcribe_rate_limit(request.remote_addr)
    if reason:
        return jsonify({"error": reason}), 429

    # Per-request body cap (whole body, multipart overhead included): Werkzeug
    # stops reading past it instead of spooling an arbitrarily large upload.
    request.max_content_length = current_app.config["TRANSCRIBE_MAX_BYTES"]
    try:
        audio = request.files.get("audio")
    except RequestEntityTooLarge:
        return jsonify({"error": "That recording is too long. Please record a shorter one."}), 413
    if audio is None:
        return jsonify({"error": "Missing audio file"}), 400

    try:
        text = transcribe_audio(audio)
    except SpeechToTextError as e:
        return jsonify({"error": str(e)}), 502

    return jsonify({
        "text": text
    }), 200
