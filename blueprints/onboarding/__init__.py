# app/blueprints/onboarding/__init__.py

from flask import Blueprint

onboarding_bp = Blueprint(
    "onboarding",
    __name__,
    url_prefix="/onboarding",
    template_folder="templates",
    static_folder="static"
)
