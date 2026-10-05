# app/models/admin.py

from extensions.database import db


class AdminUser(db.Model):
    """An app operator (admin). Authorization source of truth.

    Not a WorkerProfile. Has no password — authentication is delegated to an
    external OIDC issuer via AdminIdentity rows. Email is a display/provisioning
    attribute; the durable auth key lives on AdminIdentity as (issuer, subject).
    """
    __tablename__ = "admin_users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)

    identities = db.relationship(
        "AdminIdentity",
        back_populates="admin_user",
        cascade="all, delete-orphan",
    )


class AdminIdentity(db.Model):
    """How an AdminUser authenticates. (issuer, subject) = OIDC (iss, sub)."""
    __tablename__ = "admin_identities"

    id = db.Column(db.Integer, primary_key=True)
    admin_user_id = db.Column(
        db.Integer,
        db.ForeignKey("admin_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    issuer = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

    admin_user = db.relationship("AdminUser", back_populates="identities")

    __table_args__ = (
        db.UniqueConstraint("issuer", "subject", name="uq_admin_identity_issuer_subject"),
        db.UniqueConstraint("admin_user_id", "issuer", name="uq_admin_identity_user_issuer"),
    )
