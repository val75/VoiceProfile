# Production Deployment

A living document for taking VoiceProfile off the Flask dev server and onto a
proper production setup. It records **what we changed, why, and the concepts
behind each decision** so the reasoning isn't lost.

**Status:** in progress
**Branch:** `chore/production-deploy`
**Last updated:** 2026-08-05

---

## Goal

The app currently runs via `flask run`, which ships Werkzeug's development
server — explicitly not for production. Replace it with a production WSGI
server (gunicorn) supervised by systemd, and close the surrounding gaps
(reproducible builds, durable OTP store, backups) without changing the public
URL or the Cloudflare setup.

---

## Architecture

Two bare-metal Ubuntu servers:

- **App server** — runs the Flask app + PostgreSQL.
- **DGX-2** — runs Whisper (speech-to-text) and the LLM (profile extraction),
  reachable from the app server over a private link. Never internet-exposed.

Public traffic reaches the app entirely through a **Cloudflare Tunnel**
(`cloudflared`), so there are no inbound ports open on the app server and TLS
is terminated at the Cloudflare edge.

```
Browser ──HTTPS──> Cloudflare edge ──tunnel──> cloudflared ──HTTP──> gunicorn 127.0.0.1:5001
                                                  (app server)         │
                                                                       ├─> PostgreSQL (localhost)
                                                                       └─> DGX-2 (private net)
                                                                             ├─ Whisper
                                                                             └─ LLM
```

**Why no nginx.** In a classic deployment nginx terminates TLS, accepts public
traffic, and reverse-proxies to the app. Here Cloudflare + `cloudflared` already
do all of that. Adding nginx would just be a third proxy serving a handful of
static files — more to misconfigure, no benefit. "Production means nginx" is
really "production means don't expose the dev server directly," which the tunnel
+ gunicorn already satisfy.

**Binding.** Gunicorn listens on `127.0.0.1:5001` (loopback only). `cloudflared`
dials that same address. Nothing else can reach the app. Binding `0.0.0.0`
would re-expose it on the public IP and must be avoided.

---

## Concepts

### WSGI — Web Server Gateway Interface

WSGI (PEP 3333) is a Python **standard** that defines how a web server hands an
HTTP request to a Python app and gets a response back. It's a contract, not a
program. A "WSGI app" is simply a callable taking the request environment and a
`start_response` function and returning the response body.

Because Flask speaks this contract, any WSGI-compliant server can run it. That
lets us split two different jobs that `flask run` mashes together:

| Job                                                              | Who does it            |
|------------------------------------------------------------------|------------------------|
| Speak HTTP, manage processes/threads, handle concurrency, survive load | WSGI **server** (gunicorn) |
| Routes, templates, business logic                                | WSGI **app** (Flask)   |

`flask run` uses Werkzeug's built-in dev server for the first job — single-worker
and unhardened, "do not use in production" per its own docs. Gunicorn is a real
WSGI server built for it: process management, concurrency, timeouts, restarts. It
knows nothing about Flask; it just needs a callable that honors the WSGI contract.

**`wsgi.py`** is the introduction between them:

```python
from app import create_app
app = create_app()          # `app` is the WSGI callable gunicorn drives
```

`gunicorn wsgi:app` means "import `app` from `wsgi.py` and drive it." It's a
separate file because `app.py` only builds the app inside
`if __name__ == "__main__"`, which runs when you *execute* `app.py` but not when
gunicorn *imports* it. `wsgi.py` exposes a ready-built `app` for that import.

WSGI is **synchronous** — a request occupies its worker/thread until done. That's
why we use `gthread` workers: our requests spend most of their time *waiting* on
the DGX, and threads let a worker handle other requests during that wait. (The
async cousin, ASGI, powers frameworks like FastAPI; not relevant here.)

### The timeout chain

The innermost timeout must fire first, so our code can return a meaningful error
instead of the user getting a bare gateway timeout:

```
Whisper client 90s   <   Cloudflare edge 100s   <   gunicorn 120s
```

- **Cloudflare edge (100s)** — fixed on non-Enterprise plans; can't change it.
- **gunicorn (120s)** — must exceed the edge, or gunicorn kills a request the
  edge is still waiting on.
- **Whisper client (90s)** — must be under the edge, so a slow transcription is
  caught in our code and rendered as a real error, not a 524 at the edge.

If recordings ever get long enough to approach 90s of Whisper time, the fix is
not a bigger timeout but returning a job ID immediately and polling for the
result — a documented escape hatch, not built yet.

---

## Change log

### Section 2 — Repo & dependency hygiene ✅

Make the app reproducible from a clean clone.

- Stopped ignoring `migrations/`; committed the 4 Alembic scripts + scaffolding
  so the schema history lives in git, not only on the laptop.
- Rewrote `requirements.txt` with pinned versions. Added `Flask-Babel` (was
  missing entirely — the app can't boot without it) and `requests` (used by
  `stt_service`). Dropped unused `whisper`/`vosk`/`pydub` (STT runs over HTTP to
  the DGX). Added `gunicorn`.
- Narrowed the blanket `*.md` ignore so real docs (`CLAUDE.md`, `docs/`) are
  versioned while `tasks/` planning notes stay local.

**Known follow-up:** the migration chain's root is *"add onboarding fields,"* not
*"create tables"* — the base schema was bootstrapped with `flask init-db`
(`db.create_all()`). A rebuild from a totally empty database needs `init-db`
first (or an `alembic stamp`), not `flask db upgrade` alone. Production already
has its schema, so this only matters for a future from-scratch rebuild.

### Section 1 — Gunicorn WSGI serving ✅

- Added `wsgi.py` exposing `app = create_app()` for gunicorn to import.
- Added `gunicorn.conf.py`: loopback bind `127.0.0.1:5001`, `gthread` workers,
  timeout chain (see above), logs to stdout/stderr for journald. Workers pinned
  to **1** for now (see Section 3) — bumps to 3 once OTP is in Postgres.
- Dropped the Whisper client timeout 180s → 90s to fit under the edge limit.
- Smoke-tested locally: gunicorn boots 3 gthread workers and serves `/` with
  HTTP 200.

Run it: `gunicorn -c gunicorn.conf.py wsgi:app`

### Section 3 — systemd service ✅ (unit + runbook; server cutover pending)

Added `deploy/voiceprofile.service` — a systemd unit that runs gunicorn as
`cato-user` from `/home/cato-user/VoiceProfile`, starts on boot, restarts on
crash, and logs to journald. Replaces the manual `flask run`.

**Interim concurrency:** workers pinned to **1** (see `gunicorn.conf.py`) until
OTP moves to Postgres (Section 4), so the in-memory OTP store keeps working.
One worker × 4 threads = 4 concurrent requests, fine for a pilot. Bumps to 3
in Section 4.

**Worker/DB ordering:** `Wants=` (not `Requires=`) `postgresql.service`, so a
Postgres blip doesn't force-stop the app. On Ubuntu `postgresql.service` is a
wrapper that starts the real `postgresql@16-main.service`.

#### Cutover runbook (run on the app server)

The server tracks `main` (no i18n live). Deploying this branch is safe. Code
reaches the server via `git pull`.

```bash
# 1. From the laptop: publish the branch
git push -u origin chore/production-deploy

# 2. On the server, in /home/cato-user/VoiceProfile
git fetch origin
git checkout chore/production-deploy
git pull

# 3. Sync dependencies (gunicorn + other newly pinned deps)
venv/bin/pip install -r requirements.txt

# 4. Apply any pending migrations (idempotent; DB is already populated)
venv/bin/flask db upgrade

# 5. Test gunicorn on a temp port WITHOUT disturbing the running `flask run`
venv/bin/gunicorn -c gunicorn.conf.py --bind 127.0.0.1:8099 wsgi:app
#    in another shell:
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8099/   # expect 200
#    then Ctrl-C the test gunicorn

# 6. Install the unit
sudo cp deploy/voiceprofile.service /etc/systemd/system/voiceprofile.service
sudo systemctl daemon-reload

# 7. Stop the old dev server (frees 127.0.0.1:5001), then start the service
#    stop `flask run` however it's currently launched (Ctrl-C / tmux / kill)
sudo systemctl enable --now voiceprofile

# 8. Verify
sudo systemctl status voiceprofile --no-pager
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5001/   # expect 200
sudo journalctl -u voiceprofile -n 30 --no-pager
#    then load https://tryout.sharegud.com (or phone on cellular)
```

**Rollback** (if gunicorn misbehaves):

```bash
sudo systemctl disable --now voiceprofile
# restart `flask run` the old way, then investigate before retrying
```

Step 7 has a few seconds of downtime between stopping `flask run` and the
service starting — acceptable for a pilot.

**Subsequent deploys** become: `git pull && venv/bin/pip install -r
requirements.txt && venv/bin/flask db upgrade && sudo systemctl restart
voiceprofile`.

**Later:** once all sections are done and merged to `main`, point the server
back at `main` (`git checkout main && git pull`) so production doesn't sit on a
feature branch.

---

## Open items

- [x] **Section 3** — systemd unit built (`deploy/voiceprofile.service`) +
  cutover runbook written. **Server cutover still to be run on the box.**
- [ ] **Section 4** — move OTP codes from the in-memory dict to PostgreSQL
  (survives restarts + multiple workers), add attempt limiting; **then bump
  gunicorn workers 1 → 3**; make `SECRET_KEY` fail loudly if unset; add
  `/healthz`; harden session cookies.
- [ ] **Section 5** — `pg_dump` backups on a timer; finalize the deploy runbook,
  including the from-scratch bootstrap note above.

### Resolved during setup

- Public-IP exposure closed: app moved to loopback, `cloudflared` ingress
  repointed to `127.0.0.1:5001`, port 5001 no longer publicly bound.
- Cloudflare tunnel bug fixed: `config.yml` and DNS now point at one
  consolidated tunnel/UUID (a mismatch had caused a 502, then an NXDOMAIN).
- Confirmed `FLASK_DEBUG=0` in production (`=1` only on the laptop) — the
  interactive debugger is not exposed to the internet.
