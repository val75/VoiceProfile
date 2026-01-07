# app/extensions/__init__.py

# Initializes extensions (e.g., database, cache, etc.)
from .database import db

__all__ = ["db"]
