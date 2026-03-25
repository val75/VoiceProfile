import os

from flask import Flask, render_template
from config import Config
from extensions.database import db, migrate
from blueprints.voice_input.routes import voice_input_bp
from blueprints.profile_builder.routes import profile_builder_bp
from blueprints.profiles.routes import profiles_bp
from blueprints.onboarding.routes import onboarding_bp


def create_app():
    myapp = Flask(__name__)
    myapp.config.from_object(Config)

    db.init_app(myapp)
    migrate.init_app(myapp, db)

    myapp.register_blueprint(voice_input_bp, url_prefix="/voice")
    myapp.register_blueprint(profile_builder_bp, url_prefix="/builder")
    myapp.register_blueprint(profiles_bp, url_prefix="/profiles")
    myapp.register_blueprint(onboarding_bp, url_prefix="/onboarding")

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

    return myapp


if __name__ == "__main__":
    app = create_app()

    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", 5001))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"

    app.run(host=host, port=port, debug=debug)
