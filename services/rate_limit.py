"""Rate limiting for OTP sends (SMS-bombing, cost abuse) and for the public
transcribe endpoint (Whisper cost abuse)."""
from datetime import datetime, timedelta, timezone
from typing import Optional

from flask import current_app

from extensions.database import db
from models.otp_request import OTPRequest
from models.transcribe_request import TranscribeRequest


def check_otp_rate_limit(phone: str, ip: Optional[str]) -> Optional[str]:
    """Enforce OTP send limits. Returns None if the send is allowed (and records
    the request), or a short user-facing reason string if it should be blocked.

    Three guards, all backed by the otp_requests table so they hold across
    gunicorn workers:
      - a per-phone cooldown (rapid re-sends to the same number),
      - a per-phone hourly cap (bombing one victim),
      - a per-IP hourly cap (one source cycling many numbers).
    """
    cfg = current_app.config
    cooldown = cfg["OTP_RESEND_COOLDOWN_SECONDS"]
    per_phone = cfg["OTP_MAX_PER_PHONE_PER_HOUR"]
    per_ip = cfg["OTP_MAX_PER_IP_PER_HOUR"]

    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)

    # Housekeeping: drop this phone's rows older than the window so the table
    # stays bounded. (Rows outside the window don't affect the counts below.)
    OTPRequest.query.filter(
        OTPRequest.phone == phone, OTPRequest.created_at < hour_ago
    ).delete(synchronize_session=False)

    # Cooldown between sends to the same number.
    cooldown_cutoff = now - timedelta(seconds=cooldown)
    if OTPRequest.query.filter(
        OTPRequest.phone == phone, OTPRequest.created_at > cooldown_cutoff
    ).count() > 0:
        db.session.commit()
        return "Please wait a moment before requesting another code."

    # Per-phone hourly cap.
    if OTPRequest.query.filter(
        OTPRequest.phone == phone, OTPRequest.created_at > hour_ago
    ).count() >= per_phone:
        db.session.commit()
        return "Too many code requests for this number. Please try again later."

    # Per-IP hourly cap (stops one source cycling through many numbers).
    if ip and OTPRequest.query.filter(
        OTPRequest.ip == ip, OTPRequest.created_at > hour_ago
    ).count() >= per_ip:
        db.session.commit()
        return "Too many requests. Please try again later."

    # Allowed — record it.
    db.session.add(OTPRequest(phone=phone, ip=ip, created_at=now))
    db.session.commit()
    return None


def check_transcribe_rate_limit(ip: Optional[str]) -> Optional[str]:
    """Per-IP hourly cap on /voice/transcribe, backed by the transcribe_requests
    table so it holds across gunicorn workers. Returns None if allowed (and
    records the request), or a short user-facing reason string if blocked."""
    per_ip = current_app.config["TRANSCRIBE_MAX_PER_IP_PER_HOUR"]

    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)

    # Housekeeping: rows outside the window never count, so keep the table bounded.
    TranscribeRequest.query.filter(
        TranscribeRequest.created_at < hour_ago
    ).delete(synchronize_session=False)

    if TranscribeRequest.query.filter(
        TranscribeRequest.ip == ip, TranscribeRequest.created_at > hour_ago
    ).count() >= per_ip:
        db.session.commit()
        return "Too many recordings from this network. Please try again later, or type your review."

    db.session.add(TranscribeRequest(ip=ip, created_at=now))
    db.session.commit()
    return None
