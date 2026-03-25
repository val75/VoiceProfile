# app/blueprints/onboarding/routes.py

from flask import render_template, request, jsonify, redirect, url_for, session
from extensions.database import db
from models.profile import WorkerProfile
from . import onboarding_bp
from services.stt_service import transcribe_audio, SpeechToTextError
import re

ONBOARDING_STEPS = [
    "name",
    "name_confirm",
    "skills",
    "experience",
    "availability",
    "review"
]

QUESTIONS = {
    'name':         "What is your full name?",
    'skills':       "What skills or types of work are you experienced in?",
    'experience':   "How many years of experience do you have, and can you describe your work background?",
    'availability': "What days and hours are you available to work?",
}

# Ordered steps (excluding name_confirm which is an intermediate state)
VOICE_STEPS = ["name", "skills", "experience", "availability"]


def clean_transcribed_name(transcription: str) -> str:
    """
    Cleans Whisper transcription for name step.
    Handles uppercase, weird casing, and common speech prefixes.
    """

    if not transcription:
        return ""

    # Normalize whitespace first
    text = transcription.strip()

    # Remove common spoken prefixes (case-insensitive)
    text = re.sub(
        r"^(my name is|this is|i am|i'm)\s+",
        "",
        text,
        flags=re.IGNORECASE
    )

    # Convert to lowercase first (normalizes ALL CAPS cases)
    text = text.lower()

    # Capitalize each word properly
    text = text.title()

    # Remove accidental trailing punctuation
    text = text.strip(" .,!")

    return text


@onboarding_bp.route('/question/<question_id>')
def show_question(question_id):
    question_text = QUESTIONS.get(question_id, 'Question not found')

    return render_template(
        'onboarding/record_question.html',
        question_id=question_id,
        question_text=question_text
    )


@onboarding_bp.route("/transcribe", methods=["POST"])
def transcribe():
    if "audio" not in request.files:
        return jsonify({"error": "Missing audio file"}), 400

    audio = request.files["audio"]
    question_id = request.form.get('question_id', 'unknown')

    try:
        text = transcribe_audio(audio)
    except SpeechToTextError as e:
        return jsonify({"error": str(e)}), 502

    return jsonify({
        'text': text,
        'question_id': question_id
    })

# ---------------------------------------------------------------------------
# Onboarding flow
# ---------------------------------------------------------------------------


# @onboarding_bp.route("/start1")
# def start_onboarding():
#    """Create a fresh profile and kick off the onboarding flow."""
#    profile = WorkerProfile()
#    db.session.add(profile)
#    db.session.commit()
#
#    return redirect(url_for("onboarding.name_step", profile_id=profile.id))


@onboarding_bp.route("/start")
def start_onboarding():
    """Create a fresh profile and kick off the onboarding flow."""
    profile = WorkerProfile()
    db.session.add(profile)
    db.session.commit()

    # Store profile_id in session so subsequent steps can access it without
    # passing it through every URL (though we also accept it as a URL param).
    session['profile_id'] = profile.id

    return redirect(url_for("onboarding.name_step", profile_id=profile.id))


# @onboarding_bp.route("/<int:profile_id>/name")
# def name_step1(profile_id):
#    profile = WorkerProfile.query.get_or_404(profile_id)
#
#    return render_template(
#        "onboarding/name.html",
#        profile_id=profile.id
#    )

@onboarding_bp.route("/<int:profile_id>/name")
def name_step(profile_id):
    """Render the generic recording page for the name question."""
    profile = WorkerProfile.query.get_or_404(profile_id)

    return render_template(
        "onboarding/record_question.html",
        question_id='name',
        question_text = QUESTIONS['name'],
        # Pass profile_id so the template can POST to the right transcribe URL.
        transcribe_url=url_for('onboarding.name_transcribe', profile_id=profile.id)
    )


# @onboarding_bp.route("/<int:profile_id>/name/transcribe", methods=["POST"])
# def name_transcribe(profile_id):
#    profile = WorkerProfile.query.get_or_404(profile_id)
#
#    if "audio" not in request.files:
#        return jsonify({"error": "Missing audio file"}), 400
#
#    audio = request.files["audio"]
#
#    try:
#        transcript = transcribe_audio(audio)
#    except SpeechToTextError as e:
#        return jsonify({"error": str(e)}), 502
#
    # Extract structured name
    # name = extract_name(transcript)
#
#    cleaned_name = clean_transcribed_name(transcript)
#
    # Update profile
#    profile.name = cleaned_name
    # profile.transcripts = {**profile.transcripts, "name": transcript}
#    profile.onboarding_state = "name_confirm"
#
#    db.session.commit()
#
#    return jsonify({
#        "success": True,
#        "name": cleaned_name,
#        "needs_confirmation": True
#    })

@onboarding_bp.route("/<int:profile_id>/name/transcribe", methods=["POST"])
def name_transcribe(profile_id):
    """Receive the audio, transcribe it, clean the name, and persist it."""
    profile = WorkerProfile.query.get_or_404(profile_id)

    if "audio" not in request.files:
        return jsonify({"error": "Missing audio file"}), 400

    audio = request.files["audio"]

    try:
        transcript = transcribe_audio(audio)
    except SpeechToTextError as e:
        return jsonify({"error": str(e)}), 502

    cleaned_name = clean_transcribed_name(transcript)

    # Persist the cleaned name and raw transcript, then move state forward.
    profile.name = cleaned_name
    profile.transcripts = {**(profile.transcripts or {}), "name": transcript}
    profile.onboarding_state = "name_confirm"
    db.session.commit()

    return jsonify({
        "success": True,
        "name": cleaned_name,
        "confirm_url": url_for("onboarding.confirm_name", profile_id=profile.id)
    })


# @onboarding_bp.route("/<int:profile_id>/name/confirm", methods=["POST"])
# def confirm_name(profile_id):
#    profile = WorkerProfile.query.get_or_404(profile_id)
#
#    data = request.get_json()
#    confirmed = data.get("confirmed")
#
#    if confirmed:
#        profile.onboarding_step = "skills"
#        db.session.commit()
#
#        return jsonify({
#            "success": True,
#            "next_url": url_for("onboarding.skills_step")
#        })
#    else:
        # Reset name if rejected
#        profile.name = None
#        profile.onboarding_step = "name"
#        db.session.commit()
#
#        return jsonify({
#            "success": True,
#            "retry": True
#        })

@onboarding_bp.route("/<int:profile_id>/name/confirm", methods=["POST"])
def confirm_name(profile_id):
    """
        The client sends { confirmed: true/false }
        - Confirmed  → advance to the skills step
        - Rejected   → wipe the name and send the user back to re-record
    """

    profile = WorkerProfile.query.get_or_404(profile_id)

    data = request.get_json()
    confirmed = data.get("confirmed")

    if confirmed:
        edited_text = data.get("edited_text")
        if edited_text is not None:
            edited_text = edited_text.strip()
            if not edited_text:
                return jsonify({"error": "Name cannot be empty"}), 400
            profile.name = edited_text

        profile.onboarding_state = "skills"
        db.session.commit()

        return jsonify({
            "success": True,
            "next_url": url_for("onboarding.voice_step", profile_id=profile.id, step="skills")
        })
    else:
        # Reset so the user can try again
        profile.name = None
        profile.onboarding_state = "name"
        db.session.commit()

        return jsonify({
            "success": True,
            "retry": True,
            "retry_url": url_for("onboarding.name_step", profile_id=profile.id)
        })


# ---------------------------------------------------------------------------
# Generic voice steps: skills, experience, availability
# ---------------------------------------------------------------------------

GENERIC_STEPS = VOICE_STEPS[1:]  # ["skills", "experience", "availability"]


@onboarding_bp.route("/<int:profile_id>/<step>")
def voice_step(profile_id, step):
    """Render the recording page for skills, experience, or availability."""
    if step not in GENERIC_STEPS:
        return "Not found", 404

    profile = WorkerProfile.query.get_or_404(profile_id)

    return render_template(
        "onboarding/record_question.html",
        question_id=step,
        question_text=QUESTIONS[step],
        transcribe_url=url_for("onboarding.voice_transcribe", profile_id=profile.id, step=step)
    )


@onboarding_bp.route("/<int:profile_id>/<step>/transcribe", methods=["POST"])
def voice_transcribe(profile_id, step):
    """Transcribe audio for a generic voice step and store it."""
    if step not in GENERIC_STEPS:
        return jsonify({"error": "Invalid step"}), 404

    profile = WorkerProfile.query.get_or_404(profile_id)

    if "audio" not in request.files:
        return jsonify({"error": "Missing audio file"}), 400

    try:
        transcript = transcribe_audio(request.files["audio"])
    except SpeechToTextError as e:
        return jsonify({"error": str(e)}), 502

    profile.transcripts = {**(profile.transcripts or {}), step: transcript}
    profile.onboarding_state = step
    db.session.commit()

    return jsonify({
        "success": True,
        "transcription": transcript,
        "confirm_url": url_for("onboarding.voice_confirm", profile_id=profile.id, step=step)
    })


@onboarding_bp.route("/<int:profile_id>/<step>/confirm", methods=["POST"])
def voice_confirm(profile_id, step):
    """Confirm or reject the transcription for a generic voice step."""
    if step not in GENERIC_STEPS:
        return jsonify({"error": "Invalid step"}), 404

    profile = WorkerProfile.query.get_or_404(profile_id)

    data = request.get_json() or {}
    confirmed = data.get("confirmed")

    if confirmed:
        edited_text = data.get("edited_text")
        if edited_text is not None:
            edited_text = edited_text.strip()
            if not edited_text:
                return jsonify({"error": "Text cannot be empty"}), 400
            transcripts = dict(profile.transcripts or {})
            transcripts[step] = edited_text
            profile.transcripts = transcripts

        step_index = VOICE_STEPS.index(step)
        is_last = step_index == len(VOICE_STEPS) - 1

        if is_last:
            profile.onboarding_state = "review"
            db.session.commit()
            next_url = url_for("profiles.get_profile", profile_id=profile.id)
        else:
            next_step = VOICE_STEPS[step_index + 1]
            profile.onboarding_state = next_step
            db.session.commit()
            next_url = url_for("onboarding.voice_step", profile_id=profile.id, step=next_step)

        return jsonify({"success": True, "next_url": next_url})
    else:
        transcripts = dict(profile.transcripts or {})
        transcripts.pop(step, None)
        profile.transcripts = transcripts
        db.session.commit()

        return jsonify({
            "success": True,
            "retry_url": url_for("onboarding.voice_step", profile_id=profile.id, step=step)
        })