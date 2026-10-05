from functools import wraps

from flask import session, redirect, url_for, current_app, g

from extensions.database import db
from models.admin import AdminUser

# Session marker for the offline dev fallback (see routes.login).
DEV_ADMIN = "dev"


def admin_required(f):
    """Require a live admin session.

    session["admin"] holds an AdminUser id (int), or DEV_ADMIN under the local
    dev fallback. The admin row is re-checked on every request so disabling or
    deleting an admin revokes existing sessions immediately. The dev marker is
    honoured only while the app runs in debug mode.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        ident = session.get("admin")
        if ident == DEV_ADMIN and current_app.debug:
            g.admin = None
            return f(*args, **kwargs)
        admin = db.session.get(AdminUser, ident) if type(ident) is int else None
        if admin is None or not admin.is_active:
            if ident is not None:
                current_app.logger.info("Admin session revoked: %r", ident)
            session.pop("admin", None)
            return redirect(url_for("admin.login"))
        g.admin = admin
        return f(*args, **kwargs)
    return decorated


def current_admin():
    """The AdminUser for this request, or None under the dev fallback.

    Only meaningful inside an @admin_required view.
    """
    return g.get("admin")
