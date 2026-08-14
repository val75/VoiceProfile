# app/models/profile.py

from extensions.database import db
from sqlalchemy.dialects.postgresql import JSONB


class WorkerProfile(db.Model):
    __tablename__ = "profiles"

    id = db.Column(db.Integer, primary_key=True)

    # Structured identity fields
    name = db.Column(db.String(120))
    phone_number = db.Column(db.String(20), unique=True, index=True)

    # System fields
    onboarding_state = db.Column(db.String(50), default="intro")
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    # When the user opted in to receive SMS verification codes (proof of consent).
    sms_consent_at = db.Column(db.DateTime(timezone=True))

    # Flexible AI profile
    profile_data = db.Column(JSONB)
    transcripts = db.Column(JSONB)

    # Profile photo (resized JPEG). Deferred so the bytes load only when served.
    photo = db.deferred(db.Column(db.LargeBinary))
    photo_mime = db.Column(db.String(50))


