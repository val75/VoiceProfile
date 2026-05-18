import logging
import secrets
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# In-memory store: phone -> (code, expires_at)
# Does not survive server restarts — acceptable for the stub.
_pending: dict[str, tuple[str, datetime]] = {}

_CODE_TTL_MINUTES = 5


class OTPError(Exception):
    pass


def send_code(phone: str) -> None:
    """Generate a 6-digit OTP and log it to the terminal (stub — no real SMS)."""
    code = str(secrets.randbelow(1_000_000)).zfill(6)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_CODE_TTL_MINUTES)
    _pending[phone] = (code, expires_at)
    # In production this line is replaced by a Twilio Verify API call.
    print(f"[OTP STUB] Code for {phone}: {code}", flush=True)


def verify_code(phone: str, code: str) -> bool:
    """Return True if the code matches and has not expired. Consumes the code on success."""
    entry = _pending.get(phone)
    if not entry:
        return False

    stored_code, expires_at = entry
    if datetime.now(timezone.utc) > expires_at:
        _pending.pop(phone, None)
        return False

    if not secrets.compare_digest(stored_code, code.strip()):
        return False

    # Single-use: remove after successful verification.
    _pending.pop(phone, None)
    return True
