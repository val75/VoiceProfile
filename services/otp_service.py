import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app

from extensions.database import db
from models.otp import OTPCode

logger = logging.getLogger(__name__)

_CODE_TTL_MINUTES = 5
_MAX_ATTEMPTS = 5


class OTPError(Exception):
    pass


def _hash_code(phone: str, code: str) -> str:
    """Keyed HMAC-SHA256 of the code.

    Keyed with SECRET_KEY so a leaked database or log can't be brute-forced
    offline without also holding the app secret. The phone is mixed in so the
    same code for different numbers hashes differently.
    """
    secret = current_app.config["SECRET_KEY"].encode()
    msg = f"{phone}:{code}".encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def _deliver_code(phone: str, code: str) -> None:
    """Deliver the code to the user's phone.

    Sends an SMS via Twilio when the TWILIO_* config is present; otherwise logs
    the code (local dev, or an environment where SMS isn't configured yet).
    Raises OTPError if Twilio is configured but the send fails, so the caller
    can show a friendly "couldn't send" message.
    """
    cfg = current_app.config
    sid = cfg.get("TWILIO_ACCOUNT_SID")
    token = cfg.get("TWILIO_AUTH_TOKEN")
    sender = cfg.get("TWILIO_FROM_NUMBER")

    # OTP_DELIVERY=log forces logging even when Twilio is configured — handy for
    # testing or while an A2P 10DLC campaign is still pending. "auto" (default)
    # sends via Twilio when configured, otherwise logs.
    if cfg.get("OTP_DELIVERY") == "log" or not (sid and token and sender):
        current_app.logger.info("[OTP STUB] Code for %s: %s", phone, code)
        return

    from twilio.rest import Client
    from twilio.base.exceptions import TwilioRestException

    # `sender` may be a phone number (+1...) or a Messaging Service SID (MG...).
    # US A2P 10DLC ties the number to a Messaging Service, so support both:
    # an MG value routes through the Messaging Service, anything else is a from-number.
    params = {"to": phone, "body": f"Your ShareGud verification code is {code}"}
    if sender.startswith("MG"):
        params["messaging_service_sid"] = sender
    else:
        params["from_"] = sender

    try:
        Client(sid, token).messages.create(**params)
    except TwilioRestException as e:
        current_app.logger.error("Twilio send failed for %s: %s", phone, e)
        raise OTPError("Could not send verification code") from e


def send_code(phone: str) -> str:
    """Generate a 6-digit OTP, store its hash, deliver it, and return it.

    Delivery goes through Twilio when configured, else the code is logged (dev
    or not-yet-configured). The returned code is only surfaced by the caller in
    debug mode.
    """
    code = str(secrets.randbelow(1_000_000)).zfill(6)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_CODE_TTL_MINUTES)

    # One active code per phone: clear any previous codes first.
    OTPCode.query.filter_by(phone=phone).delete()
    db.session.add(
        OTPCode(
            phone=phone,
            code_hash=_hash_code(phone, code),
            expires_at=expires_at,
        )
    )
    db.session.commit()

    _deliver_code(phone, code)
    return code


def verify_code(phone: str, code: str) -> bool:
    """Return True if the code matches, is unexpired, and attempts remain.

    Consumes the code on success. Each failed guess counts toward a per-code
    attempt limit; once exhausted (or expired) the code is destroyed.
    """
    entry = (
        OTPCode.query.filter_by(phone=phone)
        .order_by(OTPCode.created_at.desc())
        .first()
    )
    if entry is None:
        return False

    now = datetime.now(timezone.utc)
    expires_at = entry.expires_at
    if expires_at.tzinfo is None:  # tolerate a naive value from the driver
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if now > expires_at or entry.attempts >= _MAX_ATTEMPTS:
        db.session.delete(entry)
        db.session.commit()
        return False

    if hmac.compare_digest(entry.code_hash, _hash_code(phone, code.strip())):
        db.session.delete(entry)  # single-use
        db.session.commit()
        return True

    entry.attempts += 1
    db.session.commit()
    return False
