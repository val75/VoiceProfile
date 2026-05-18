from flask import Blueprint, request, redirect, url_for, render_template, session, flash
from extensions.database import db
from models.profile import WorkerProfile
from models.review import Review

reviews_bp = Blueprint(
    "reviews", __name__,
    template_folder="templates",
    static_folder="static",
)


@reviews_bp.route("/<int:profile_id>")
def public_profile(profile_id):
    profile = WorkerProfile.query.get_or_404(profile_id)
    reviews = Review.query.filter_by(profile_id=profile_id).order_by(Review.created_at.desc()).all()
    return render_template("reviews/public_profile.html", profile=profile, reviews=reviews)


@reviews_bp.route("/<int:profile_id>/review/new", methods=["GET", "POST"])
def new_review(profile_id):
    profile = WorkerProfile.query.get_or_404(profile_id)

    if session.get("profile_id") == profile_id:
        flash("You cannot review your own profile.")
        return redirect(url_for("reviews.public_profile", profile_id=profile_id))

    if request.method == "POST":
        reviewer_name = request.form.get("reviewer_name", "").strip() or "Anonymous"
        rating = request.form.get("rating", type=int)
        content = request.form.get("content", "").strip()
        transcript = request.form.get("transcript", "").strip() or None

        if not rating or not (1 <= rating <= 5):
            flash("Please select a rating.")
            return render_template("reviews/new_review.html", profile=profile)
        if not content:
            flash("Please write something in your review.")
            return render_template("reviews/new_review.html", profile=profile)

        review = Review(
            profile_id=profile_id,
            reviewer_name=reviewer_name,
            rating=rating,
            content=content,
            transcript=transcript,
        )
        db.session.add(review)
        db.session.commit()
        return redirect(url_for("reviews.thanks", profile_id=profile_id))

    return render_template("reviews/new_review.html", profile=profile)


@reviews_bp.route("/<int:profile_id>/review/thanks")
def thanks(profile_id):
    profile = WorkerProfile.query.get_or_404(profile_id)
    return render_template("reviews/thanks.html", profile=profile)
