import pytest
from sqlalchemy.exc import IntegrityError

from extensions.database import db
from models.admin import AdminUser, AdminIdentity


def test_create_admin_with_identity(app):
    admin = AdminUser(email="a@example.com", is_active=True)
    db.session.add(admin)
    db.session.flush()
    ident = AdminIdentity(admin_user_id=admin.id, issuer="https://accounts.google.com", subject="sub-1")
    db.session.add(ident)
    db.session.commit()
    assert admin.identities[0].subject == "sub-1"
    assert ident.admin_user.email == "a@example.com"
    assert admin.is_active is True


def test_issuer_subject_unique(app):
    a = AdminUser(email="a@example.com")
    b = AdminUser(email="b@example.com")
    db.session.add_all([a, b])
    db.session.flush()
    db.session.add(AdminIdentity(admin_user_id=a.id, issuer="iss", subject="dup"))
    db.session.commit()
    db.session.add(AdminIdentity(admin_user_id=b.id, issuer="iss", subject="dup"))
    with pytest.raises(IntegrityError):
        db.session.commit()


def test_one_identity_per_issuer_per_admin(app):
    a = AdminUser(email="a@example.com")
    db.session.add(a)
    db.session.flush()
    db.session.add(AdminIdentity(admin_user_id=a.id, issuer="iss", subject="s1"))
    db.session.commit()
    db.session.add(AdminIdentity(admin_user_id=a.id, issuer="iss", subject="s2"))
    with pytest.raises(IntegrityError):
        db.session.commit()


def test_cascade_delete_removes_identities(app):
    a = AdminUser(email="a@example.com")
    db.session.add(a)
    db.session.flush()
    db.session.add(AdminIdentity(admin_user_id=a.id, issuer="iss", subject="s1"))
    db.session.commit()
    db.session.delete(a)
    db.session.commit()
    assert AdminIdentity.query.count() == 0
