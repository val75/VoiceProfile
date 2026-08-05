# Gunicorn configuration for VoiceProfile.
# Run with: gunicorn -c gunicorn.conf.py wsgi:app
#
# See docs/deployment/production-deployment.md for the full rationale.

# --- Where to listen -------------------------------------------------------
# Loopback only. Cloudflare Tunnel (cloudflared) runs on this same box and
# dials 127.0.0.1:5001; nothing should reach the app except through the tunnel.
# Do NOT bind 0.0.0.0 here — that would re-expose the app on the public IP.
bind = "127.0.0.1:5001"

# --- Concurrency -----------------------------------------------------------
# Requests are I/O-bound: most of their time is spent waiting on the DGX
# (Whisper up to 90s, LLM up to 30s), not on CPU. Threaded workers let one
# worker serve other requests while a thread waits. 3 workers x 4 threads =
# 12 concurrent requests, generous for a pilot on a single box.
workers = 3
worker_class = "gthread"
threads = 4

# --- Timeout chain ---------------------------------------------------------
# The innermost timeout must fire first so our code can return a real error
# instead of the client getting a bare gateway timeout:
#   Whisper client 90s  <  Cloudflare edge 100s  <  gunicorn 120s
# gunicorn's timeout must exceed the edge limit, or gunicorn would kill a
# request the edge is still willing to wait on.
timeout = 120
graceful_timeout = 30
keepalive = 5

# --- Logging ---------------------------------------------------------------
# Log to stdout/stderr; systemd/journald captures it (Section 3).
accesslog = "-"
errorlog = "-"
loglevel = "info"
