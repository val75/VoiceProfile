# app/services/profile_service.py
"""Whole-profile deletion, for worker "delete my data" requests."""
from flask import current_app

from extensions.database import db
from models.otp import OTPCode
from models.otp_request import OTPRequest
from models.recording import VoiceRecording
from models.review import Review


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
