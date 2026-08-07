# app/models/otp.py

from extensions.database import db


class OTPCode(db.Model):
    """A one-time login code, stored as a keyed hash (never plaintext).

    Persisting these in Postgres (rather than a per-process dict) lets codes
    survive restarts/deploys and be shared across gunicorn workers, and gives
    us a place to count failed attempts for brute-force protection.
    """
    __tablename__ = "otp_codes"

    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), nullable=False, index=True)
    # HMAC-SHA256 hex digest of the code, keyed with SECRET_KEY.
    code_hash = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
