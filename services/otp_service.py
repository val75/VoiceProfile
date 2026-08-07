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


def send_code(phone: str) -> str:
    """Generate a 6-digit OTP, store its hash, log it, and return it.

    The caller may surface the returned code in debug mode. Replacing the
    print() with an SMS provider is the only change needed to go live.
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

    print(f"[OTP STUB] Code for {phone}: {code}", flush=True)
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
