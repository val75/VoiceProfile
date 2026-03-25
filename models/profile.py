# app/models/profile.py

from extensions.database import db
from sqlalchemy.dialects.postgresql import JSONB


class WorkerProfile(db.Model):
    __tablename__ = "profiles"

    id = db.Column(db.Integer, primary_key=True)

    # Structured identity fields
    name = db.Column(db.String(120))
    phone_number = db.Column(db.String(20))

    # System fields
    onboarding_state = db.Column(db.String(50), default="name")
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    # Flexible AI profile
    profile_data = db.Column(JSONB)
    transcripts = db.Column(JSONB)


