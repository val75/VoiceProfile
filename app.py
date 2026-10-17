import logging
import os

import click
from flask import Flask, render_template
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config
from extensions.database import db, migrate
from extensions.oauth import oauth
from blueprints.auth.routes import auth_bp
from blueprints.voice_input.routes import voice_input_bp
from blueprints.profile_builder.routes import profile_builder_bp
from blueprints.profiles.routes import profiles_bp
from blueprints.onboarding.routes import onboarding_bp
from blueprints.reviews.routes import reviews_bp
from blueprints.admin.routes import admin_bp
from services.timezones import zone_is_valid
from cli import profile_cli, recordings_cli


def create_app(test_config=None):
    myapp = Flask(__name__)
    myapp.config.from_object(Config)
    if test_config:
        myapp.config.update(test_config)

    # Flask's logger defaults to WARNING when not in debug, hiding logger.info
    # output. Surface INFO in production too (journald captures stderr).
    if not myapp.debug:
        myapp.logger.setLevel(logging.INFO)

    # Behind Cloudflare Tunnel the app sees plain HTTP from cloudflared on
    # loopback. Trust one hop of X-Forwarded-* so request.is_secure, the URL
    # scheme, host, and client IP reflect the real browser, not the proxy.
    # Safe because the app binds loopback only — nothing but cloudflared can
    # reach it to forge these headers.
    myapp.wsgi_app = ProxyFix(myapp.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(myapp)
    migrate.init_app(myapp, db)
    oauth.init_app(myapp)
    # `oauth` is a module-global and create_app runs once per test. Authlib does
    # NOT raise on a duplicate name: register() overwrites the config in
    # `_registry`, but create_client() keeps returning the client cached in
    # `_clients` from the first call -- so the new config is silently ignored.
    # Register only once so the first app's config is the one that is live.
    if "admin_idp" not in oauth._registry:
        oauth.register(
            name="admin_idp",
            server_metadata_url=myapp.config["OIDC_DISCOVERY_URL"],
            client_id=myapp.config["OIDC_CLIENT_ID"],
            client_secret=myapp.config["OIDC_CLIENT_SECRET"],
            client_kwargs={"scope": "openid email profile"},
        )
    if not myapp.debug and not all(
        myapp.config.get(k) for k in ("OIDC_DISCOVERY_URL", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET")
    ):
        myapp.logger.warning(
            "Admin login is not configured (OIDC_DISCOVERY_URL / OIDC_CLIENT_ID / "
            "OIDC_CLIENT_SECRET unset); admin login will fail until they are set."
        )
    tz_name = myapp.config.get("ADMIN_TIMEZONE")
    if tz_name and not zone_is_valid(tz_name):
        myapp.logger.warning("ADMIN_TIMEZONE %r is not a known time zone; using UTC.", tz_name)

    myapp.register_blueprint(auth_bp)
    myapp.register_blueprint(voice_input_bp, url_prefix="/voice")
    myapp.register_blueprint(profile_builder_bp, url_prefix="/builder")
    myapp.register_blueprint(profiles_bp, url_prefix="/profiles")
    myapp.register_blueprint(onboarding_bp, url_prefix="/onboarding")
    myapp.register_blueprint(reviews_bp, url_prefix="/p")
    myapp.register_blueprint(admin_bp, url_prefix=myapp.config["ADMIN_URL_PREFIX"])

    @myapp.cli.command("init-db")
    def init_db():
        """Initialize the database."""
        from extensions.database import db
        db.create_all()
        print("✅ Database initialized successfully.")

    @myapp.cli.command("reset-db")
    def reset_db():
        """Drop and recreate all database tables."""
        from flask import current_app
        from extensions.database import db

        print("Connecting to:", current_app.config["SQLALCHEMY_DATABASE_URI"])

        if not current_app.debug:
            print("❌ Refusing to reset DB outside debug mode")
            return

        db.drop_all()
        db.create_all()
        print("🔥 Database dropped and recreated successfully.")

    @myapp.cli.command("add-admin")
    @click.argument("email")
    def add_admin_cmd(email):
        """Provision an admin by email (identity links on first login)."""
        from services.admin_service import add_admin
        admin = add_admin(email)
        if not admin.is_active:
            raise click.ClickException(
                f"Admin {admin.email} exists but is disabled; "
                f"run `flask enable-admin {admin.email}` to re-enable."
            )
        print(f"✅ Admin provisioned: {admin.email} (id={admin.id})")

    @myapp.cli.command("enable-admin")
    @click.argument("email")
    def enable_admin_cmd(email):
        """Re-enable a disabled admin by email."""
        from services.admin_service import enable_admin
        admin = enable_admin(email)
        if admin is None:
            raise click.ClickException(f"No admin found for {email}")
        print(f"✅ Admin enabled: {admin.email}")

    @myapp.cli.command("disable-admin")
    @click.argument("email")
    def disable_admin_cmd(email):
        """Disable an admin by email."""
        from services.admin_service import disable_admin
        admin = disable_admin(email)
        if admin is None:
            raise click.ClickException(f"No admin found for {email}")
        print(f"🚫 Admin disabled: {admin.email}")

    @myapp.cli.command("list-admins")
    def list_admins_cmd():
        """List all admins and their linked identities."""
        from services.admin_service import list_admins
        for a in list_admins():
            status = "active" if a.is_active else "disabled"
            issuers = ", ".join(i.issuer for i in a.identities) or "no identities yet"
            print(f"{a.email:40} [{status}] {issuers}")

    myapp.cli.add_command(recordings_cli)
    myapp.cli.add_command(profile_cli)

    @myapp.route('/')
    def home():
        return render_template('index.html')

    # Public legal pages — linked from the SMS consent opt-in and referenced in
    # the A2P 10DLC campaign registration. Must be reachable without login.
    @myapp.route('/terms')
    def terms():
        return render_template('terms.html')

    @myapp.route('/privacy')
    def privacy():
        return render_template('privacy.html')

    @myapp.route('/healthz')
    def healthz():
        """Readiness probe: 200 if the DB answers, 503 otherwise."""
        try:
            db.session.execute(text("SELECT 1"))
            return {"status": "ok"}, 200
        except Exception:
            myapp.logger.exception("healthz DB check failed")
            return {"status": "db unavailable"}, 503

    return myapp


if __name__ == "__main__":
    app = create_app()

    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", 5001))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"

    app.run(host=host, port=port, debug=debug)
