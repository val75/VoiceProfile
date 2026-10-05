import os

# Must be set before importing app/config (evaluated at import time).
os.environ.setdefault("FLASK_DEBUG", "1")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from sqlalchemy import event
from sqlalchemy.pool import StaticPool

from app import create_app
from extensions.database import db as _db
from models.admin import AdminUser, AdminIdentity


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
    })
    with application.app_context():
        engine = _db.engine

        @event.listens_for(engine, "connect")
        def _fk_pragma(dbapi_con, con_record):
            dbapi_con.execute("PRAGMA foreign_keys=ON")

        # Create only the admin tables — the worker tables use Postgres JSONB
        # and are not needed (nor creatable) under SQLite for these tests.
        AdminUser.__table__.create(engine)
        AdminIdentity.__table__.create(engine)
        yield application
        _db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def session(app):
    return _db.session
