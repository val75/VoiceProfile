# Production WSGI entrypoint.
# Gunicorn imports this: `gunicorn -c gunicorn.conf.py wsgi:app`
# The dev server (`python app.py`) still uses the __main__ block in app.py.

from app import create_app

app = create_app()
