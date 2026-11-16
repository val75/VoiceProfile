# VoiceProfile app image (gunicorn + Flask). Built by .github/workflows/build.yml
# and pushed as ghcr.io/val75/voiceprofile:<git sha>.
#
#   docker build --target test .     # run the test suite (what CI runs first)
#   docker build .                   # runtime image (last stage)
#
# Configuration comes only from the environment (compose env_file); .env is
# never copied in (.dockerignore). See docs/deployment/production-deployment.md.

FROM python:3.12-slim AS base
LABEL org.opencontainers.image.source="https://github.com/val75/VoiceProfile"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
RUN useradd --system --uid 10001 --no-create-home --home-dir /app app

# Test stage: the unit tests use in-memory SQLite, so no database is needed.
FROM base AS test
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
USER app
RUN python -m pytest -q -p no:cacheprovider

# Runtime stage (default target).
FROM base AS runtime
USER app
# gunicorn.conf.py binds 127.0.0.1:5001 unless GUNICORN_BIND is set.
EXPOSE 5001
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
