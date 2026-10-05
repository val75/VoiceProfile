# app/services/admin_service.py

from datetime import datetime, timezone

from flask import current_app
from sqlalchemy.exc import IntegrityError

from extensions.database import db
from models.admin import AdminUser, AdminIdentity


def _now():
    return datetime.now(timezone.utc)


def _touch(admin, name):
    """Record a successful login; backfill the display name if we don't have one."""
    admin.last_login_at = _now()
    if name and not admin.name:
        admin.name = name


def resolve_admin(issuer, subject, email, email_verified, name=None):
    """Resolve a verified OIDC identity to an active AdminUser, or None.

    1. Durable path: match an existing (issuer, subject) identity.
    2. First login: require a verified email, then link to a pre-provisioned
       admin_users row or auto-provision one for a break-glass ADMIN_EMAILS.
       A disabled admin is always denied — never re-provisioned. An admin who
       already has an identity at this issuer is denied (a new subject for a
       known email means the email was reassigned at the provider).
    Any lost race on the first-login inserts is denied cleanly (returns None).
    """
    identity = AdminIdentity.query.filter_by(issuer=issuer, subject=subject).first()
    if identity is not None:
        admin = identity.admin_user
        if not admin.is_active:
            return None
        _touch(admin, name)
        db.session.commit()
        return admin

    if not email_verified or not email:
        return None
    email = email.strip().lower()

    try:
        admin = AdminUser.query.filter_by(email=email).first()
        if admin is not None:
            if not admin.is_active:
                return None
            linked = AdminIdentity.query.filter_by(admin_user_id=admin.id, issuer=issuer).first()
            if linked is not None:
                return None
        elif email in current_app.config["ADMIN_EMAILS"]:
            admin = AdminUser(email=email, is_active=True)
            db.session.add(admin)
            db.session.flush()
        else:
            return None

        db.session.add(AdminIdentity(admin_user_id=admin.id, issuer=issuer, subject=subject))
        _touch(admin, name)
        db.session.commit()
    except IntegrityError:
        # Concurrent first login won the insert (duplicate email or identity).
        db.session.rollback()
        return None
    return admin


def add_admin(email):
    """Provision an admin_users row (no identity yet). Idempotent."""
    email = email.strip().lower()
    admin = AdminUser.query.filter_by(email=email).first()
    if admin is not None:
        return admin
    admin = AdminUser(email=email, is_active=True)
    db.session.add(admin)
    db.session.commit()
    return admin


def disable_admin(email):
    admin = AdminUser.query.filter_by(email=email.strip().lower()).first()
    if admin is not None:
        admin.is_active = False
        db.session.commit()
    return admin


def enable_admin(email):
    admin = AdminUser.query.filter_by(email=email.strip().lower()).first()
    if admin is not None:
        admin.is_active = True
        db.session.commit()
    return admin


def list_admins():
    return AdminUser.query.order_by(AdminUser.created_at).all()
