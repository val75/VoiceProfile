# app/models/otp_request.py

from datetime import datetime, timezone

from extensions.database import db


class OTPRequest(db.Model):
    """A record of one OTP *send* request, used for rate limiting.

    Guards against SMS-bombing a victim's number and burning SMS budget: we
    count recent rows per phone and per IP before allowing another send.
    """
    __tablename__ = "otp_requests"

    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), nullable=False, index=True)
    ip = db.Column(db.String(45), index=True)  # client IP (IPv6-safe length)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
