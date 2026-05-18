from extensions.database import db


class Review(db.Model):
    __tablename__ = "reviews"

    id            = db.Column(db.Integer, primary_key=True)
    profile_id    = db.Column(db.Integer, db.ForeignKey("profiles.id"), nullable=False, index=True)
    reviewer_name = db.Column(db.String(120), default="Anonymous")
    rating        = db.Column(db.Integer, nullable=False)
    content       = db.Column(db.Text, nullable=False)
    transcript    = db.Column(db.Text, nullable=True)
    created_at    = db.Column(db.DateTime, server_default=db.func.now())

    profile = db.relationship(
        "WorkerProfile",
        backref=db.backref("reviews", lazy="dynamic", order_by="Review.created_at.desc()")
    )
