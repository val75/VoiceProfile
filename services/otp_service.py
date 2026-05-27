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


def send_code(phone: str) -> str:
    """Generate a 6-digit OTP, log it, and return it (caller may surface it in debug mode)."""
    code = str(secrets.randbelow(1_000_000)).zfill(6)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_CODE_TTL_MINUTES)
    _pending[phone] = (code, expires_at)
    print(f"[OTP STUB] Code for {phone}: {code}", flush=True)
    return code


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
