# app/blueprints/onboarding/routes.py

from flask import render_template, request, jsonify, redirect, url_for, session
from extensions.database import db
from models.profile import WorkerProfile
from . import onboarding_bp
from blueprints.auth.decorators import profile_owner_required
from services.stt_service import transcribe_audio, SpeechToTextError
from services.nlp_service import extract_profile_data, ExtractionError
from services.recording_service import save_take, record_result, mark_decision
from services.profile_service import COMPLETED
import re
import logging

logger = logging.getLogger(__name__)

ONBOARDING_STEPS = [
    "intro",
    "name",
    "name_confirm",
    "story",
    "availability",
    "review"
]

# Short, ordered labels shown on the intro screen so the user knows what's coming.
INTRO_OUTLINE = [
    "Your name",
    "Your work experience — what you've done, how long, and where",
    "The days and hours you're available",
]

QUESTIONS = {
    'name':         "What is your full name?",
    'story':        "Tell me about your work experience — every kind of work you've done, how long you did each, and where if you remember. You have up to 3 minutes. Take your time.",
    'availability': "What days and hours are you available to work?",
}

# Status line under the record button before the worker taps it.
RECORD_PROMPTS = {
    'name':         "Tap the green button to record your name.",
    'story':        "Tap the green button to record your work story.",
    'availability': "Tap the green button to record when you can work.",
}

# Ordered steps (excluding name_confirm which is an intermediate state)
VOICE_STEPS = ["name", "story", "availability"]

# How long (seconds) the worker may speak per voice step. Story is capped at 3 min.
STEP_MAX_SECONDS = {"story": 180}

# Session key for a name take awaiting the worker's confirmation.
PENDING_NAME_KEY = "pending_name_transcript"

# Longest name profiles.name holds (also keeps a pending take small in the session cookie).
NAME_MAX_LENGTH = WorkerProfile.__table__.c.name.type.length


def _advance(profile, state):
    """Record onboarding progress. A completed profile stays completed while it's
    re-edited (e.g. "Re-record story"): the state gates whether it's public, and the
    step-to-step flow runs on each response's next_url, not on the stored state."""
    if profile.onboarding_state != COMPLETED:
        profile.onboarding_state = state


def _set_extracted(profile, data):
    """Store fresh extraction output. A completed profile is public, so a re-edit's
    output waits in profile_data_draft until the worker saves the review page."""
    if profile.onboarding_state == COMPLETED:
        profile.profile_data_draft = data
    else:
        profile.profile_data = data


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


def _parse_duration_ms(raw):
    """Browser-reported take length in ms; None unless a sane non-negative int."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= 24 * 3600 * 1000 else None


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
    """Entry point kept for backwards compatibility. Auth now handles profile creation."""
    return redirect(url_for("auth.login"))


# @onboarding_bp.route("/<int:profile_id>/name")
# def name_step1(profile_id):
#    profile = WorkerProfile.query.get_or_404(profile_id)
#
#    return render_template(
#        "onboarding/name.html",
#        profile_id=profile.id
#    )

@onboarding_bp.route("/<int:profile_id>/intro")
@profile_owner_required
def intro(profile_id):
    """Welcome screen: explain the purpose and outline the steps before Q1."""
    profile = WorkerProfile.query.get_or_404(profile_id)

    return render_template(
        "onboarding/intro.html",
        profile=profile,
        outline=INTRO_OUTLINE,
        begin_url=url_for("onboarding.name_step", profile_id=profile.id),
    )


@onboarding_bp.route("/<int:profile_id>/name")
@profile_owner_required
def name_step(profile_id):
    """Render the generic recording page for the name question."""
    profile = WorkerProfile.query.get_or_404(profile_id)

    return render_template(
        "onboarding/record_question.html",
        question_id='name',
        question_text = QUESTIONS['name'],
        record_prompt=RECORD_PROMPTS['name'],
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
@profile_owner_required
def name_transcribe(profile_id):
    """Receive the audio, transcribe it, and hold the name until the worker confirms it."""
    profile = WorkerProfile.query.get_or_404(profile_id)

    # A new take replaces any earlier one, so a failed take can't leave the old one confirmable.
    session.pop(PENDING_NAME_KEY, None)

    if "audio" not in request.files:
        return jsonify({"error": "Missing audio file"}), 400

    audio = request.files["audio"]

    try:
        transcript = transcribe_audio(audio)
    except SpeechToTextError as e:
        return jsonify({"error": str(e)}), 502

    cleaned_name = clean_transcribed_name(transcript)
    if not cleaned_name:
        return jsonify({"error": "We didn't catch a name. Please try again."}), 400
    if len(cleaned_name) > NAME_MAX_LENGTH:
        return jsonify({"error": "Please say just your name."}), 400

    # The name is public, so a re-recorded one must not replace it before it's
    # confirmed: keep the take in the session; confirm_name saves it.
    session[PENDING_NAME_KEY] = transcript
    _advance(profile, "name_confirm")
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
@profile_owner_required
def confirm_name(profile_id):
    """
        The client sends { confirmed: true/false, edited_text? }
        - Confirmed  → save the pending name (edited text wins) and advance to the story step
        - Rejected   → drop the pending name (the saved one is untouched) and re-record
    """

    profile = WorkerProfile.query.get_or_404(profile_id)

    data = request.get_json()
    confirmed = data.get("confirmed")

    if confirmed:
        transcript = session.get(PENDING_NAME_KEY)
        if transcript is None:
            return jsonify({"error": "Please record your name first."}), 400

        edited_text = data.get("edited_text")
        if edited_text is not None:
            edited_text = edited_text.strip()
            if not edited_text:
                return jsonify({"error": "Name cannot be empty"}), 400
            if len(edited_text) > NAME_MAX_LENGTH:
                return jsonify({"error": "That name is too long."}), 400

        session.pop(PENDING_NAME_KEY)
        profile.name = edited_text if edited_text is not None else clean_transcribed_name(transcript)
        profile.transcripts = {**(profile.transcripts or {}), "name": transcript}
        _advance(profile, "story")
        db.session.commit()

        return jsonify({
            "success": True,
            "next_url": url_for("onboarding.voice_step", profile_id=profile.id, step="story")
        })
    else:
        # Let the user try again; a previously saved name stays as it was.
        session.pop(PENDING_NAME_KEY, None)
        _advance(profile, "name")
        db.session.commit()

        return jsonify({
            "success": True,
            "retry": True,
            "retry_url": url_for("onboarding.name_step", profile_id=profile.id)
        })


# ---------------------------------------------------------------------------
# Generic voice steps: story, availability
# ---------------------------------------------------------------------------

GENERIC_STEPS = VOICE_STEPS[1:]  # ["story", "availability"]


@onboarding_bp.route("/<int:profile_id>/<step>")
@profile_owner_required
def voice_step(profile_id, step):
    """Render the recording page for skills, experience, or availability."""
    if step not in GENERIC_STEPS:
        return "Not found", 404

    profile = WorkerProfile.query.get_or_404(profile_id)

    return render_template(
        "onboarding/record_question.html",
        question_id=step,
        question_text=QUESTIONS[step],
        question_hint=None,
        record_prompt=RECORD_PROMPTS[step],
        max_seconds=STEP_MAX_SECONDS.get(step),
        transcribe_url=url_for("onboarding.voice_transcribe", profile_id=profile.id, step=step),
        is_last_step=(step == GENERIC_STEPS[-1]),
    )


@onboarding_bp.route("/<int:profile_id>/<step>/transcribe", methods=["POST"])
@profile_owner_required
def voice_transcribe(profile_id, step):
    """Transcribe audio for a generic voice step and store it."""
    if step not in GENERIC_STEPS:
        return jsonify({"error": "Invalid step"}), 404

    profile = WorkerProfile.query.get_or_404(profile_id)

    if "audio" not in request.files:
        return jsonify({"error": "Missing audio file"}), 400

    audio = request.files["audio"]
    # Raw-audio capture (best-effort; no-op unless VOICE_RECORDING_CAPTURE).
    take_id = save_take(profile.id, step, audio,
                        _parse_duration_ms(request.form.get("duration_ms")))

    try:
        transcript = transcribe_audio(audio)
    except SpeechToTextError as e:
        record_result(take_id, error=str(e))
        return jsonify({"error": str(e)}), 502

    record_result(take_id, transcript=transcript)

    profile.transcripts = {**(profile.transcripts or {}), step: transcript}
    _advance(profile, step)
    db.session.commit()

    return jsonify({
        "success": True,
        "transcription": transcript,
        "confirm_url": url_for("onboarding.voice_confirm", profile_id=profile.id, step=step)
    })


@onboarding_bp.route("/<int:profile_id>/<step>/confirm", methods=["POST"])
@profile_owner_required
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

        # Before touching the profile: capture commits / rolls back only its own work.
        mark_decision(profile.id, step, accepted=True, edited_text=edited_text)

        if edited_text is not None:
            transcripts = dict(profile.transcripts or {})
            transcripts[step] = edited_text
            profile.transcripts = transcripts

        step_index = VOICE_STEPS.index(step)
        is_last = step_index == len(VOICE_STEPS) - 1

        if is_last:
            try:
                extracted = extract_profile_data(profile.transcripts or {})
            except ExtractionError as e:
                logger.error("Profile extraction failed for %d: %s", profile.id, e)
                extracted = {"extraction_error": str(e)}
            _set_extracted(profile, extracted)

            _advance(profile, "review")
            db.session.commit()
            next_url = url_for("onboarding.review_step", profile_id=profile.id, draft=1)
        else:
            next_step = VOICE_STEPS[step_index + 1]
            _advance(profile, next_step)
            db.session.commit()
            next_url = url_for("onboarding.voice_step", profile_id=profile.id, step=next_step)

        return jsonify({"success": True, "next_url": next_url})
    else:
        mark_decision(profile.id, step, accepted=False)

        transcripts = dict(profile.transcripts or {})
        transcripts.pop(step, None)
        profile.transcripts = transcripts
        db.session.commit()

        return jsonify({
            "success": True,
            "retry_url": url_for("onboarding.voice_step", profile_id=profile.id, step=step)
        })


# ---------------------------------------------------------------------------
# Review step: show extracted profile data for validation
# ---------------------------------------------------------------------------

@onboarding_bp.route("/<int:profile_id>/review")
@profile_owner_required
def review_step(profile_id):
    """Render the profile review page with extracted structured data."""
    profile = WorkerProfile.query.get_or_404(profile_id)
    profile_data = profile.profile_data or {}
    # A re-edit arrives with ?draft=1 to show its unsaved extraction. Edit profile (no flag)
    # shows the live data, so an abandoned draft never resurfaces; a failed one shows the
    # live data with the error banner rather than an empty form.
    draft = profile.profile_data_draft if request.args.get("draft") else None
    has_error = "extraction_error" in (draft or profile_data)
    if draft and not has_error:
        profile_data = draft

    return render_template(
        "onboarding/review.html",
        profile=profile,
        profile_data=profile_data,
        has_error=has_error,
    )


@onboarding_bp.route("/<int:profile_id>/review", methods=["POST"])
@profile_owner_required
def save_review(profile_id):
    """Save the user-edited profile data."""
    profile = WorkerProfile.query.get_or_404(profile_id)

    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing profile data"}), 400

    profile.profile_data = data
    profile.profile_data_draft = None
    profile.onboarding_state = "completed"
    db.session.commit()

    return jsonify({"success": True, "next_url": url_for("profiles.view_profile", profile_id=profile.id)})


@onboarding_bp.route("/<int:profile_id>/review/re-extract", methods=["POST"])
@profile_owner_required
def re_extract(profile_id):
    """Re-run LLM extraction on existing transcripts."""
    profile = WorkerProfile.query.get_or_404(profile_id)

    try:
        extracted = extract_profile_data(profile.transcripts or {})
        _set_extracted(profile, extracted)
        db.session.commit()
        return jsonify({"success": True, "profile_data": extracted})
    except ExtractionError as e:
        return jsonify({"error": str(e)}), 502