# app/config.py

import os
from dotenv import load_dotenv

load_dotenv()

_DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"


def _require_secret_key() -> str:
    """Return SECRET_KEY, or fail loudly in production if it is unset.

    A missing key must never silently fall back to a guessable default: that
    would let anyone forge session cookies and OTP hashes. In debug (local dev)
    we allow an obvious throwaway so the laptop stays convenient.
    """
    key = os.getenv("SECRET_KEY")
    if key:
        return key
    if _DEBUG:
        return "dev-only-insecure-key"
    raise RuntimeError(
        "SECRET_KEY is not set. Refusing to start in production without it."
    )


class Config:
    DEBUG = _DEBUG
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = _require_secret_key()
    WHISPER_URL = os.getenv("WHISPER_URL")
    WHISPER_API_KEY = os.getenv("WHISPER_API_KEY")
    LLM_URL = os.getenv("LLM_URL", "http://localhost:11434/v1")
    LLM_MODEL = os.getenv("LLM_MODEL", "mistral:7b-instruct")
    LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "30"))

    # Twilio (SMS OTP delivery). If any of these is unset, OTP codes are logged
    # instead of sent — so local dev and not-yet-configured envs still work.
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
    TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")

    # OTP delivery mode: "auto" (send via Twilio when configured, else log the
    # code) or "log" (always log, never send — for testing, or while an A2P
    # campaign is still pending). Lets you keep Twilio creds set but pause sends.
    OTP_DELIVERY = os.getenv("OTP_DELIVERY", "auto")

    # Default region for parsing phone numbers with no explicit +country-code.
    # US for the initial US-based MVP; change (e.g. "RO") as the user base shifts.
    PHONE_DEFAULT_REGION = os.getenv("PHONE_DEFAULT_REGION", "US")

    # OTP send rate limiting (guards against SMS-bombing / Twilio cost abuse).
    OTP_RESEND_COOLDOWN_SECONDS = int(os.getenv("OTP_RESEND_COOLDOWN_SECONDS", "60"))
    OTP_MAX_PER_PHONE_PER_HOUR = int(os.getenv("OTP_MAX_PER_PHONE_PER_HOUR", "5"))
    OTP_MAX_PER_IP_PER_HOUR = int(os.getenv("OTP_MAX_PER_IP_PER_HOUR", "20"))

    # --- Session cookie hardening -----------------------------------------
    # HttpOnly: JS can't read the cookie (XSS mitigation).
    # SameSite=Lax: not sent on cross-site requests (CSRF mitigation).
    # Secure: only sent over HTTPS. Disabled in debug so localhost dev over
    # plain HTTP still works; enabled in production (served via Cloudflare TLS).
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = not _DEBUG
