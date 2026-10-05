from unittest.mock import patch

from sqlalchemy.exc import IntegrityError

from extensions.database import db
from models.admin import AdminUser, AdminIdentity
from services.admin_service import resolve_admin, add_admin, disable_admin, list_admins

GOOG = "https://accounts.google.com"


def test_break_glass_first_login_provisions_and_links(app):
    admin = resolve_admin(GOOG, "sub-1", "founder@example.com", True)
    assert admin is not None
    assert admin.email == "founder@example.com"
    assert AdminIdentity.query.filter_by(issuer=GOOG, subject="sub-1").count() == 1
    assert admin.last_login_at is not None


def test_preprovisioned_email_links_on_first_login(app):
    add_admin("ops@example.com")
    admin = resolve_admin(GOOG, "sub-2", "ops@example.com", True)
    assert admin is not None
    assert AdminIdentity.query.filter_by(issuer=GOOG, subject="sub-2").count() == 1


def test_durable_match_survives_email_change(app):
    add_admin("ops@example.com")
    resolve_admin(GOOG, "sub-3", "ops@example.com", True)
    # Same subject, different (unverified even) email — still resolves.
    admin = resolve_admin(GOOG, "sub-3", "new@example.com", False)
    assert admin is not None
    assert admin.email == "ops@example.com"


def test_unknown_and_unprovisioned_is_denied(app):
    assert resolve_admin(GOOG, "sub-x", "stranger@example.com", True) is None


def test_unverified_first_login_denied(app):
    assert resolve_admin(GOOG, "sub-4", "founder@example.com", False) is None


def test_disabled_admin_denied(app):
    resolve_admin(GOOG, "sub-5", "founder@example.com", True)
    disable_admin("founder@example.com")
    assert resolve_admin(GOOG, "sub-5", "founder@example.com", True) is None


def test_add_admin_is_idempotent_and_lowercases(app):
    a = add_admin("Ops@Example.com")
    b = add_admin("ops@example.com")
    assert a.id == b.id
    assert a.email == "ops@example.com"


def test_list_admins(app):
    add_admin("a@example.com")
    add_admin("b@example.com")
    assert {u.email for u in list_admins()} == {"a@example.com", "b@example.com"}


def test_disabled_break_glass_new_device_denied(app):
    # Founder logs in once (break-glass), then is disabled, then returns on a
    # NEW device (new subject). Must be denied cleanly (None), not crash.
    resolve_admin(GOOG, "sub-dev1", "founder@example.com", True)
    disable_admin("founder@example.com")
    result = resolve_admin(GOOG, "sub-dev2", "founder@example.com", True)
    assert result is None


def test_reassigned_email_new_subject_denied(app):
    # Founder links via sub-a. A NEW subject for the same email at the same
    # issuer means the email was reassigned at the provider → deny.
    resolve_admin(GOOG, "sub-a", "founder@example.com", True)
    assert resolve_admin(GOOG, "sub-b", "founder@example.com", True) is None
    assert AdminIdentity.query.count() == 1


def test_first_login_race_returns_none(app):
    add_admin("ops@example.com")
    err = IntegrityError("stmt", {}, Exception())
    with patch.object(db.session, "commit", side_effect=[err]):
        assert resolve_admin(GOOG, "sub-r", "ops@example.com", True) is None
    # Session was rolled back and is usable again.
    assert AdminUser.query.count() == 1
    assert AdminIdentity.query.count() == 0


def test_name_backfilled_on_first_login(app):
    admin = resolve_admin(GOOG, "sub-n", "founder@example.com", True, name="Founder")
    assert admin.name == "Founder"
    admin = resolve_admin(GOOG, "sub-n", "founder@example.com", True, name="Someone Else")
    assert admin.name == "Founder"


def test_enable_admin(app):
    from services.admin_service import enable_admin
    add_admin("ops@example.com")
    disable_admin("ops@example.com")
    assert enable_admin("Ops@Example.com").is_active is True
    assert AdminUser.query.filter_by(email="ops@example.com").first().is_active is True
    assert enable_admin("nobody@example.com") is None
