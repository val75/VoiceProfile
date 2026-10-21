# app/blueprints/voice_input/routes.py

from flask import Blueprint, request, jsonify, current_app
from services.stt_service import transcribe_audio, SpeechToTextError
from services.rate_limit import check_transcribe_rate_limit

voice_input_bp = Blueprint("voice_input", __name__, url_prefix="/voice")


def _upload_size(file_storage) -> int:
    file_storage.seek(0, 2)
    size = file_storage.tell()
    file_storage.seek(0)  # transcribe_audio reads the same upload next
    return size


@voice_input_bp.route("/transcribe", methods=["POST"])
def transcribe():
    """Public speech-to-text for anonymous voice reviews on /p/<id>.

    No login (reviewers have none), so it is size-capped and rate-limited per IP.
    request.remote_addr is the real client IP thanks to ProxyFix.
    """
    if "audio" not in request.files:
        return jsonify({"error": "Missing audio file"}), 400

    audio = request.files["audio"]

    # Size first: an oversized upload is rejected without using up the IP's quota.
    if _upload_size(audio) > current_app.config["TRANSCRIBE_MAX_BYTES"]:
        return jsonify({"error": "That recording is too long. Please record a shorter one."}), 413

    reason = check_transcribe_rate_limit(request.remote_addr)
    if reason:
        return jsonify({"error": reason}), 429

    try:
        text = transcribe_audio(audio)
    except SpeechToTextError as e:
        return jsonify({"error": str(e)}), 502

    return jsonify({
        "text": text
    }), 200
