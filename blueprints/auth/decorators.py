from functools import wraps
from flask import session, redirect, url_for, abort


def login_required(f):
    """Redirect to login if no authenticated session exists."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("profile_id"):
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def profile_owner_required(f):
    """Require login AND that the session owner matches the profile_id in the URL.

    Applies to any route with a <int:profile_id> parameter.
    Returns 403 if a logged-in user tries to access another user's profile.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("profile_id"):
            return redirect(url_for("auth.login"))
        if session["profile_id"] != kwargs.get("profile_id"):
            abort(403)
        return f(*args, **kwargs)
    return decorated
