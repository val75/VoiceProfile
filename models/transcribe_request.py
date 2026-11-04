# app/models/transcribe_request.py

from datetime import datetime, timezone

from extensions.database import db


class TranscribeRequest(db.Model):
    """A record of one accepted /voice/transcribe call, used for rate limiting.

    That endpoint is public (anonymous voice reviews use it), so each call costs
    us a Whisper run: we count recent rows per IP before allowing another.
    """
    __tablename__ = "transcribe_requests"

    id = db.Column(db.Integer, primary_key=True)
    ip = db.Column(db.String(45), index=True)  # client IP (IPv6-safe length)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
