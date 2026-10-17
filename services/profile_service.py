# app/services/profile_service.py
"""Admin view of worker profiles: counts, search, and whole-profile deletion
(for worker "delete my data" requests).

The admin list deliberately selects only bookkeeping columns: never
profile_data, transcripts or review text.
"""
import re
from typing import Optional

from flask import current_app
from sqlalchemy import exists, func, or_, select

from extensions.database import db
from models.otp import OTPCode
from models.otp_request import OTPRequest
from models.profile import WorkerProfile
from models.recording import VoiceRecording
from models.review import Review
from services.recording_service import FilterError

COMPLETED = "completed"
# Where an unfinished profile stopped, in onboarding order; name_confirm is part of "name".
STEP_LABELS = {"intro": "intro", "name": "name", "name_confirm": "name",
               "story": "story", "availability": "availability", "review": "review"}
STATUSES = ("completed", "incomplete")
REVIEW_FILTERS = ("has", "none")
_PHONE_LIKE = re.compile(r"[\d\s().+\-]+")


def _step_label(state: Optional[str]) -> str:
    return STEP_LABELS.get(state or "intro", state)


def _has_review():
    return exists().where(Review.profile_id == WorkerProfile.id)


def _extraction_error():
    return WorkerProfile.profile_data["extraction_error"].as_string().isnot(None)


def _incomplete():
    return or_(WorkerProfile.onboarding_state.is_(None),
               WorkerProfile.onboarding_state != COMPLETED)


def profile_counts() -> dict:
    """Whole-database totals for the admin profiles page."""
    total = WorkerProfile.query.count()
    by_state = db.session.query(WorkerProfile.onboarding_state, func.count()) \
        .group_by(WorkerProfile.onboarding_state).all()
    completed, stopped = 0, {}
    for state, n in by_state:
        if state == COMPLETED:
            completed = n
        else:
            label = _step_label(state)
            stopped[label] = stopped.get(label, 0) + n
    order = list(dict.fromkeys(STEP_LABELS.values()))
    stopped_at = {k: stopped[k] for k in sorted(
        stopped, key=lambda k: (order.index(k) if k in order else len(order), k))}
    return {
        "total": total,
        "completed": completed,
        "incomplete": total - completed,
        "stopped_at": stopped_at,
        "extraction_errors": WorkerProfile.query.filter(_incomplete(), _extraction_error()).count(),
        "with_reviews": WorkerProfile.query.filter(_has_review()).count(),
    }


def search_profiles(q: Optional[str] = None, status: Optional[str] = None,
                    reviews: Optional[str] = None):
    """Admin rows (bookkeeping columns only), newest first.

    q: only digits and phone formatting -> those digits match inside the phone
    number; anything else is a case-insensitive "contains" on the name.
    """
    status, reviews, q = (status or "").strip(), (reviews or "").strip(), (q or "").strip()
    if status and status not in STATUSES:
        raise FilterError(f"Unknown status: {status} (use {' or '.join(STATUSES)})")
    if reviews and reviews not in REVIEW_FILTERS:
        raise FilterError(f"Unknown reviews filter: {reviews} (use {' or '.join(REVIEW_FILTERS)})")

    review_count = select(func.count(Review.id)) \
        .where(Review.profile_id == WorkerProfile.id).scalar_subquery()
    recording_count = select(func.count(VoiceRecording.id)) \
        .where(VoiceRecording.profile_id == WorkerProfile.id).scalar_subquery()
    query = db.session.query(
        WorkerProfile.id, WorkerProfile.name, WorkerProfile.phone_number,
        WorkerProfile.onboarding_state, WorkerProfile.created_at, WorkerProfile.updated_at,
        WorkerProfile.photo.isnot(None).label("has_photo"),
        _extraction_error().label("extraction_error"),
        review_count.label("review_count"), recording_count.label("recording_count"),
    )
    if q:
        digits = re.sub(r"\D", "", q)
        if digits and _PHONE_LIKE.fullmatch(q):
            query = query.filter(WorkerProfile.phone_number.contains(digits))
        else:
            query = query.filter(WorkerProfile.name.icontains(q, autoescape=True))
    if status == COMPLETED:
        query = query.filter(WorkerProfile.onboarding_state == COMPLETED)
    elif status:
        query = query.filter(_incomplete())
    if reviews == "has":
        query = query.filter(_has_review())
    elif reviews == "none":
        query = query.filter(~_has_review())
    return query.order_by(WorkerProfile.created_at.desc(), WorkerProfile.id.desc())


def status_label(state: Optional[str]) -> str:
    return COMPLETED if state == COMPLETED else f"stopped at {_step_label(state)}"


def delete_confirmation_code(profile) -> str:
    """What the admin types to confirm a web delete: the phone's last 4 digits, or the id."""
    digits = re.sub(r"\D", "", profile.phone_number or "")
    return digits[-4:] if len(digits) >= 4 else str(profile.id)


def profile_footprint(profile) -> dict:
    """Counts of everything delete_profile() would remove for this profile."""
    phone = profile.phone_number
    return {
        "reviews": Review.query.filter_by(profile_id=profile.id).count(),
        "recordings": VoiceRecording.query.filter_by(profile_id=profile.id).count(),
        "recording_bytes": db.session.query(
            db.func.coalesce(db.func.sum(VoiceRecording.size_bytes), 0)
        ).filter(VoiceRecording.profile_id == profile.id).scalar(),
        "otp_codes": OTPCode.query.filter_by(phone=phone).count() if phone else 0,
        "otp_requests": OTPRequest.query.filter_by(phone=phone).count() if phone else 0,
    }


def delete_profile(profile) -> dict:
    """Delete a profile and everything tied to it in one transaction; return row counts.

    reviews.profile_id has no ON DELETE CASCADE, so reviews go first. OTP rows
    are keyed by phone (no FK) and would otherwise keep the number around.
    """
    pid, phone = profile.id, profile.phone_number
    try:
        counts = {
            "reviews": Review.query.filter_by(profile_id=pid).delete(synchronize_session=False),
            "recordings": VoiceRecording.query.filter_by(profile_id=pid)
                                              .delete(synchronize_session=False),
            "otp_codes": OTPCode.query.filter_by(phone=phone)
                                      .delete(synchronize_session=False) if phone else 0,
            "otp_requests": OTPRequest.query.filter_by(phone=phone)
                                            .delete(synchronize_session=False) if phone else 0,
        }
        db.session.delete(profile)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    # app.logger: the only logger raised to INFO in production. Ids + counts only, no PII.
    current_app.logger.info("Deleted profile %s: %s", pid, counts)
    return counts
