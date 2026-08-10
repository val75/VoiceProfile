import logging
import os

from flask import Flask, render_template
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config
from extensions.database import db, migrate
from blueprints.auth.routes import auth_bp
from blueprints.voice_input.routes import voice_input_bp
from blueprints.profile_builder.routes import profile_builder_bp
from blueprints.profiles.routes import profiles_bp
from blueprints.onboarding.routes import onboarding_bp
from blueprints.reviews.routes import reviews_bp


def create_app():
    myapp = Flask(__name__)
    myapp.config.from_object(Config)

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

    myapp.register_blueprint(auth_bp)
    myapp.register_blueprint(voice_input_bp, url_prefix="/voice")
    myapp.register_blueprint(profile_builder_bp, url_prefix="/builder")
    myapp.register_blueprint(profiles_bp, url_prefix="/profiles")
    myapp.register_blueprint(onboarding_bp, url_prefix="/onboarding")
    myapp.register_blueprint(reviews_bp, url_prefix="/p")

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

    @myapp.route('/')
    def home():
        return render_template('index.html')

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
