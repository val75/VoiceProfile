# app/models/profile.py

from extensions.database import db
from sqlalchemy.dialects.postgresql import JSONB


class Profile(db.Model):
    __tablename__ = "profiles"

    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(20))
    name = db.Column(db.String(120))
    profile_data = db.Column(JSONB)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
