# app/blueprints/voice_input/routes.py

from flask import Blueprint, request, jsonify, render_template
from services.stt_service import transcribe_audio, SpeechToTextError
from services.nlp_service import extract_profile_data
from extensions.database import db
from models.profile import Profile

voice_input_bp = Blueprint("voice_input",
                           __name__,
                           url_prefix="/voice",
                           template_folder="templates",
                           static_folder="static",
                           )


@voice_input_bp.route("/record", methods=["GET"])
def record_page():
    return render_template("voice_input/record.html", debug_marker="VOICE_INPUT_RECORD")


@voice_input_bp.route("/transcribe", methods=["POST"])
def transcribe():
    if "audio" not in request.files:
        return jsonify({"error": "Missing audio file"}), 400

    audio = request.files["audio"]

    try:
        text = transcribe_audio(audio)
    except SpeechToTextError as e:
        return jsonify({"error": str(e)}), 502

    return jsonify({
        "text": text
    }), 200


@voice_input_bp.route("/upload", methods=["POST"])
def upload_audio():
    """
        Upload an audio file → transcribe → parse → save profile.
    """

    audio = request.files.get("file")
    if not audio:
        return jsonify({"error": "No audio file uploaded"}), 400

    # Step 1: Speech to text
    transcript = transcribe_audio(audio)

    # Step 2: NLP Extraction
    structured = extract_profile_data(transcript)

    # Step 3: Store in DB
    profile = Profile(name=structured.get("name"), profile_data=structured)
    db.session.add(profile)
    db.session.commit()

    return jsonify({
        "message": "Profile created successfully",
        "id": profile.id,
        "transcript": transcript,
        "structured": structured
    }), 201
