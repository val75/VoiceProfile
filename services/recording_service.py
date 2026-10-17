# app/services/recording_service.py
"""Raw voice-take capture (story / availability) for debugging and NLP test cases.

Capture is best-effort: each function here logs and swallows its own errors
(rolling back the session) so a storage problem can never change what the
worker sees. Failures log only the exception class: SQLAlchemy error text embeds
bound parameters, i.e. transcripts and edited text. Call these only while the DB session holds no pending worker
changes — the rollback would otherwise discard them too.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from flask import current_app
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import contains_eager

from extensions.database import db
from models.profile import WorkerProfile
from models.recording import VoiceRecording
from services.phone import normalize_phone
from services.timezones import local_days_to_utc_range, parse_day

logger = logging.getLogger(__name__)

CAPTURED_STEPS = ("story", "availability")
# Admin-facing names for VoiceRecording.accepted (False = the worker re-recorded).
DECISIONS = {"accepted": True, "re-recorded": False, "undecided": None}


def capture_enabled() -> bool:
    return bool(current_app.config.get("VOICE_RECORDING_CAPTURE"))


def _next_attempt(profile_id: int, step: str) -> int:
    current = (
        db.session.query(func.max(VoiceRecording.attempt))
        .filter(VoiceRecording.profile_id == profile_id, VoiceRecording.step == step)
        .scalar()
    )
    return (current or 0) + 1


def save_take(profile_id: int, step: str, file_storage,
              duration_ms: Optional[int] = None) -> Optional[int]:
    """Store one take before transcription; return its id, or None if not saved."""
    if not capture_enabled():
        return None
    try:
        try:
            audio = file_storage.read()
        finally:
            file_storage.seek(0)  # transcribe_audio reads the same upload next
        limit = current_app.config["VOICE_RECORDING_MAX_BYTES"]
        if len(audio) > limit:
            logger.warning("Voice take not saved: %d bytes over cap %d (profile=%s step=%s)",
                           len(audio), limit, profile_id, step)
            return None
        mime_type = (file_storage.content_type or "application/octet-stream")[:100]
        for _ in range(2):  # second pass only after an attempt-number clash
            take = VoiceRecording(
                profile_id=profile_id, step=step, attempt=_next_attempt(profile_id, step),
                audio=audio, mime_type=mime_type, size_bytes=len(audio),
                duration_ms=duration_ms,
            )
            db.session.add(take)
            try:
                db.session.commit()
                return take.id
            except IntegrityError:
                db.session.rollback()
        logger.error("Voice take not saved after retry (profile=%s step=%s)", profile_id, step)
        return None
    except Exception as e:
        db.session.rollback()
        logger.error("Voice take capture failed (profile=%s step=%s): %s",
                     profile_id, step, type(e).__name__)
        return None


def record_result(take_id: Optional[int], transcript: Optional[str] = None,
                  error: Optional[str] = None) -> None:
    """Attach Whisper's transcript, or the failure message, to a saved take."""
    if take_id is None:
        return
    try:
        take = db.session.get(VoiceRecording, take_id)
        if take is None:
            return
        take.transcript = transcript
        take.stt_error = error
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error("Voice take result not saved (take=%s): %s", take_id, type(e).__name__)


def mark_decision(profile_id: int, step: str, accepted: bool,
                  edited_text: Optional[str] = None) -> None:
    """Record the worker's yes/no on their latest take for this step."""
    if not capture_enabled():
        return
    try:
        take = (
            VoiceRecording.query
            .filter(VoiceRecording.profile_id == profile_id, VoiceRecording.step == step)
            .order_by(VoiceRecording.attempt.desc())
            .first()
        )
        if take is None or take.accepted is not None:
            return
        take.accepted = bool(accepted)
        take.decided_at = datetime.now(timezone.utc)
        if (accepted and edited_text is not None
                and edited_text.strip() != (take.transcript or "").strip()):
            take.edited_text = edited_text
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error("Voice take decision not saved (profile=%s step=%s): %s",
                     profile_id, step, type(e).__name__)


# ---------------------------------------------------------------------------
# Admin search (shared by the web page and the CLI)
# ---------------------------------------------------------------------------

class FilterError(ValueError):
    """A search filter the admin typed is not valid; message is user-facing."""


def build_filters(phone: Optional[str] = None, date_from: Optional[str] = None,
                  date_to: Optional[str] = None, step: Optional[str] = None,
                  decision: Optional[str] = None) -> dict:
    """Validate raw filter strings into keyword arguments for search_takes()."""
    filters = {}
    phone = (phone or "").strip()
    if phone:
        e164 = normalize_phone(phone)
        if e164 is None:
            raise FilterError(f"Not a valid phone number: {phone}")
        filters["phone_e164"] = e164
    try:
        day_from, day_to = parse_day(date_from), parse_day(date_to)
    except ValueError:
        raise FilterError("Dates must be YYYY-MM-DD")
    filters["start_utc"], filters["end_utc"] = local_days_to_utc_range(day_from, day_to)
    step = (step or "").strip()
    if step:
        if step not in CAPTURED_STEPS:
            raise FilterError(f"Unknown step: {step} (use story or availability)")
        filters["step"] = step
    decision = (decision or "").strip()
    if decision:
        if decision not in DECISIONS:
            raise FilterError(f"Unknown decision: {decision} (use {', '.join(DECISIONS)})")
        filters["decision"] = decision
    return filters


def search_takes(phone_e164=None, start_utc=None, end_utc=None, step=None,
                 decision=None, accepted_only=False):
    """Takes matching the filters, newest first; audio bytes are not loaded."""
    query = (
        VoiceRecording.query
        .join(WorkerProfile, VoiceRecording.profile_id == WorkerProfile.id)
        .options(contains_eager(VoiceRecording.profile))
    )
    if phone_e164:
        query = query.filter(WorkerProfile.phone_number == phone_e164)
    if start_utc is not None:
        query = query.filter(VoiceRecording.created_at >= start_utc)
    if end_utc is not None:
        query = query.filter(VoiceRecording.created_at < end_utc)
    if step:
        query = query.filter(VoiceRecording.step == step)
    if decision:
        query = query.filter(VoiceRecording.accepted.is_(DECISIONS[decision]))
    if accepted_only:
        query = query.filter(VoiceRecording.accepted.is_(True))
    return query.order_by(VoiceRecording.created_at.desc(), VoiceRecording.id.desc())
