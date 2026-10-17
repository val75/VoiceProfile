import os

# Must be set before importing app/config (evaluated at import time).
os.environ.setdefault("FLASK_DEBUG", "1")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from sqlalchemy import event
from sqlalchemy.pool import StaticPool

import models  # noqa: F401  (registers every table on db.metadata)
from app import create_app
from extensions.database import db as _db
from models.profile import WorkerProfile


@pytest.fixture
def app():
    application = create_app(test_config={
        "TESTING": True,
        "DEBUG": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "SQLALCHEMY_ENGINE_OPTIONS": {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        },
        "ADMIN_EMAILS": {"founder@example.com"},
        # Pin host-tunable settings so a developer's .env can't change test behaviour.
        "ADMIN_URL_PREFIX": "/admin",
        "VOICE_RECORDING_CAPTURE": False,
        "VOICE_RECORDING_MAX_BYTES": 25 * 1024 * 1024,
        "ADMIN_TIMEZONE": "",
    })
    with application.app_context():
        engine = _db.engine

        @event.listens_for(engine, "connect")
        def _fk_pragma(dbapi_con, con_record):
            dbapi_con.execute("PRAGMA foreign_keys=ON")

        # profiles' JSONB columns fall back to JSON under SQLite, so every table
        # (worker + admin) can be created here.
        _db.create_all()
        yield application
        _db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def session(app):
    return _db.session


@pytest.fixture
def make_profile(session):
    def _make(phone="+14155550100", name="Test Worker", **kw):
        profile = WorkerProfile(phone_number=phone, name=name, **kw)
        session.add(profile)
        session.commit()
        return profile
    return _make


@pytest.fixture
def make_take(session):
    from models.recording import VoiceRecording

    def _make(profile, step="story", attempt=1, audio=b"fake-audio",
              mime_type="audio/webm", **kw):
        take = VoiceRecording(profile_id=profile.id, step=step, attempt=attempt,
                              audio=audio, mime_type=mime_type, size_bytes=len(audio), **kw)
        session.add(take)
        session.commit()
        return take
    return _make
