"""Cache-busting for static files.

Every url_for('static') / url_for('<blueprint>.static') link gets ?v=<short
content hash>. A deploy that changes a script or stylesheet changes its URL, so
a browser can't pair a new page with an old cached copy; unchanged files keep
their URL and stay cached. The server ignores ?v= when serving the file.
"""
import hashlib
import os

from werkzeug.security import safe_join

# (path, mtime_ns, size) -> hash; keyed on the file's stat so an edit during
# local development gets a fresh hash without restarting the app.
_hashes = {}


def file_version(folder, filename):
    """Short content hash of folder/filename, or None if it isn't a file there."""
    path = safe_join(folder, filename) if folder else None
    if path is None or not os.path.isfile(path):
        return None
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size)
    if key not in _hashes:
        with open(path, "rb") as f:
            _hashes[key] = hashlib.sha256(f.read()).hexdigest()[:10]
    return _hashes[key]


def init_app(app):
    @app.url_defaults
    def add_static_version(endpoint, values):
        if endpoint != "static" and not endpoint.endswith(".static"):
            return
        if "v" in values or "filename" not in values:
            return
        if endpoint == "static":
            folder = app.static_folder
        else:
            bp = app.blueprints.get(endpoint.rsplit(".", 1)[0])
            folder = bp.static_folder if bp else None
        version = file_version(folder, values["filename"])
        if version:
            values["v"] = version
