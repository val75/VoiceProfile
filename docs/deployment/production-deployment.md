# Production Deployment

A living document for taking VoiceProfile off the Flask dev server and onto a
proper production setup. It records **what we changed, why, and the concepts
behind each decision** so the reasoning isn't lost.

**Status:** in progress
**Branch:** `chore/production-deploy`
**Last updated:** 2026-10-26

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
- **DGX-2** — runs Whisper (speech-to-text, `:6000`) and the LLM (vLLM, `:8000`),
  which the app server reaches over the private network (`192.168.100.0/24`, DGX at
  `192.168.100.2`). **The DGX also has a public IP**, so it is protected three ways
  (see "DGX exposure incident" in the change log):
  - **Firewall.** ufw denies all incoming traffic except SSH and `192.168.100.0/24`.
  - **Private bind.** Both services listen on `192.168.100.2` only, never `0.0.0.0`.
    vLLM 0.6.3 needs `deploy/patch-vllm-bind.sh` for this (see "vLLM bind guard").
  - **API keys.** Whisper checks `X-API-Key`; vLLM checks `Authorization: Bearer` on `/v1/*`.

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

### Running behind a proxy — ProxyFix

When a request reaches Flask, it answers questions like *"was this HTTPS?"*,
*"what host did the user type?"*, and *"what's the client IP?"* by inspecting the
**immediate TCP connection**. Behind the tunnel, that immediate connection is
not the user — it's `cloudflared` talking to gunicorn over **plain HTTP on
`127.0.0.1`**:

```
Browser ──HTTPS──> Cloudflare ──tunnel──> cloudflared ──HTTP──> Flask
 (real client)                            (127.0.0.1)     (sees plain HTTP, localhost)
```

So by default Flask concludes the request is insecure HTTP from `127.0.0.1`. The
real values aren't lost — the proxies forward them in headers (`X-Forwarded-Proto:
https`, `X-Forwarded-For: <real IP>`, `X-Forwarded-Host: …`) — but Flask ignores
those by default, because blindly trusting them would let any client lie.

**What breaks without correction:** `request.is_secure` is `False`;
`url_for(_external=True)` emits `http://` URLs (possible redirect loops /
mixed-content); secure-cookie logic gets confused; and every client looks like
`127.0.0.1` to logging or future rate-limiting.

`ProxyFix` is a small WSGI middleware that trusts a **fixed number of proxy
hops** and rewrites the request from their `X-Forwarded-*` headers:

```python
myapp.wsgi_app = ProxyFix(myapp.wsgi_app, x_for=1, x_proto=1, x_host=1)
```

`=1` means "trust exactly one hop" — the one our infrastructure adds. A client
can't spoof it, because the trusted proxy appends its own value as the last hop.
On the laptop it's a **no-op** (a direct localhost request has no `X-Forwarded-*`
headers), so it's safe to apply unconditionally. The loopback bind is what makes
trusting one hop safe: nothing but `cloudflared` can reach gunicorn to forge
headers.

### OTP codes: durable storage, hashing, attempt limits

Login codes were kept in a module-level Python dict — fine for one `flask run`
process, broken under gunicorn: a dict lives in **one** worker's memory, so a
code created in worker A is invisible to worker B (intermittent login failure),
and every restart/deploy wipes it. They now live in the `otp_codes` table.

- **Hashed, not plaintext.** We store an **HMAC-SHA256** of the code, keyed with
  `SECRET_KEY` and mixed with the phone number. A leaked DB or log can't be
  reversed into live codes without also holding the app secret.
- **Attempt limiting.** A 6-digit code is only 1,000,000 possibilities; unlimited
  guesses is an account-takeover path. Each code allows **5** failed attempts,
  then self-destructs. Expiry (5 min) and single-use-on-success still apply.
- **Same interface.** `send_code` / `verify_code` keep their signatures, so
  `auth/routes.py` is untouched. Going live with real SMS is a one-line change:
  replace the `print()` in `send_code` with a provider call.

### SECRET_KEY, sessions, and cookie flags

Flask signs the session cookie with `SECRET_KEY`; it also keys the OTP hashes
above. `config.py` used to fall back to `"dev_secret"` if the env var was
missing — meaning a misconfigured deploy would boot with a **guessable** key and
nobody would notice (forgeable sessions and OTP hashes). It now **refuses to
start** in production when `SECRET_KEY` is unset, keeping a throwaway default
only under `FLASK_DEBUG=1` for local convenience.

Session cookies are hardened: `HttpOnly` (JS can't read them — XSS mitigation),
`SameSite=Lax` (not sent cross-site — CSRF mitigation), and `Secure` (HTTPS only)
— the last gated off in debug so localhost dev over plain HTTP still works.

### /healthz

A lightweight readiness probe at `/healthz` runs `SELECT 1` and returns `200
{"status":"ok"}` when the database answers, `503` otherwise. It gives systemd,
uptime monitors, or a future load balancer a real signal that the app can serve
requests, not just that the process is alive.

### Admin login (Google OIDC)

The admin area signs in with Google (OpenID Connect via Authlib). Only the
validated ID token's `email` + `email_verified` are trusted. Env keys:

- `OIDC_DISCOVERY_URL` — `https://accounts.google.com/.well-known/openid-configuration`
- `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` — from the Google OAuth client below
- `ADMIN_EMAILS` — comma-separated break-glass allowlist of admin emails
- `ADMIN_URL_PREFIX` (optional, default `/admin`) — where the admin area is
  mounted. The repo is public, so set a non-obvious path here per host rather
  than in code. This only keeps scanners away; Google login + the allowlist
  are what actually gate access. Below, `<prefix>` means this value.

One-time Google setup: Google Cloud Console → APIs & Services → Credentials →
Create credentials → OAuth client ID → **Web application** → Authorized redirect
URI `https://<your-domain><prefix>/auth`. Changing `ADMIN_URL_PREFIX` changes
this URI, so update it in Google at the same time. The callback URL is built from the
request, so it only comes out as `https://` behind the Cloudflare Tunnel because
of the ProxyFix above — if Google reports a `redirect_uri_mismatch`, check that.

Manage admins with `flask add-admin|enable-admin|disable-admin <email>` and
`flask list-admins`. Disabling (or deleting) an admin takes effect on their next
request — existing sessions are revoked. The dev login shortcut (no Google) only
works with `FLASK_DEBUG=1` from localhost; it never fires through the tunnel.

### Backups: pg_dump, off-box copies, tested restores

`pg_dump` writes a single point-in-time snapshot of the whole database — schema
and every row, **including the photo blobs stored in `profiles`** — to one file.
Because the photos live in Postgres (not on the filesystem), this one dump is the
complete backup of everything the pilot has collected.

We use the **custom format** (`-Fc`): compressed, and restorable selectively with
`pg_restore`. A systemd timer runs it nightly, keeps 14 days locally, and copies
each dump **off the box to the DGX** over the private link. Off-box is the point:
a dump on the same disk as the database is lost with it in a disk failure — the
off-box copy is what turns "a file" into "a backup".

The discipline that's easy to skip: **restore-test it**. A dump you've never
restored can be silently truncated, mis-permissioned, or version-incompatible.
The runbook restores into a scratch database precisely so a real recovery isn't
the first time that path has ever run.

**Alerting: a dead man's switch.** A backup that fails quietly is as bad as no
backup (the off-box copy failed every night for weeks in 2026 and nobody
noticed). Each run reports its exit status to a healthchecks.io check
(`HEALTHCHECK_URL` in `.env`). healthchecks.io's own servers email you when a run
reports failure **or when no report arrives on time**. The second case is the point:
a disabled timer, a dead server or a broken script all mean "no ping", and the app
server doesn't have to be healthy enough to notice. It sends no email itself; it
only makes one outbound HTTPS request.

**Privacy policy coupling:** `templates/privacy.html` promises deleted data leaves backups
"within 14 days". The prune deletes dumps older than `RETENTION_DAYS` minus one hour
(`-mmin`, not `-mtime`, which rounds down and kept dumps an extra day). If `RETENTION_DAYS`
in `deploy/backup_db.sh` changes, update that sentence.

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

**Resolved** (see "Migration reconciliation" below): the committed history was
later squashed to a single clean initial migration that creates the base tables,
so `flask db upgrade` now builds the full schema from an empty database.

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

**Concurrency:** we chose to build Section 4 (OTP → Postgres) before cutting
over, so the OTP store is already cross-worker-safe. The service therefore runs
**3 workers × 4 threads = 12 concurrent** from the first cutover — no interim
single-worker step. (`gunicorn.conf.py` carried a temporary `workers = 1` while
Section 4 was in flight; it is now 3.)

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

**Note:** the cutover now includes `venv/bin/flask db upgrade` applying the
`otp_codes` migration (Section 4). The step is already in the runbook above.

### Section 4 — Durable OTP + security hardening ✅

- **OTP → PostgreSQL.** New `models/otp.py` (`otp_codes` table) + hand-written
  migration `b7e2a91c4f08`. Rewrote `services/otp_service.py` to store an
  HMAC-SHA256 hash of each code (keyed with `SECRET_KEY`), enforce a 5-attempt
  limit, keep 5-minute expiry and single-use, and hold one active code per
  phone. `auth/routes.py` unchanged (same `send_code` / `verify_code`).
- **`SECRET_KEY` fail-loud** (`config.py`): refuses to start in production if
  unset; throwaway default only under `FLASK_DEBUG=1`.
- **Cookie hardening** (`config.py`): `HttpOnly`, `SameSite=Lax`, `Secure`
  (off in debug).
- **`ProxyFix`** (`app.py`): trusts one hop of `X-Forwarded-*` so scheme/host/IP
  are correct behind the tunnel.
- **`/healthz`** (`app.py`): `SELECT 1` readiness probe → 200 / 503.
- **Bumped gunicorn workers 1 → 3** now that OTP is cross-worker-safe.

Verified on the laptop: migration applies (head `b7e2a91c4f08`); an OTP test
suite passes (hashing, wrong-code, single-use, 5-attempt lockout, expiry,
one-code-per-phone); gunicorn boots 3 workers; `/` and `/healthz` return 200;
`SECRET_KEY` unset in prod raises, dev fallback works.

### Section 5 — Backups + restore ✅ (setup runbook; run on the box)

Added `deploy/backup_db.sh` + `voiceprofile-backup.{service,timer}`: a nightly
`pg_dump` (custom compressed format — includes photo blobs), 14-day retention,
copied off-box to the DGX over the private network. Verified locally: the dump
is produced and `pg_restore --list` shows all tables (`profiles`, `reviews`,
`otp_codes`).

#### Backup setup (run on the app server)

```bash
# 1. One-time: SSH key from the app server to the DGX (as cato-user)
ssh-keygen -t ed25519 -f ~/.ssh/voiceprofile_backup -N ""
cat ~/.ssh/voiceprofile_backup.pub
#    ssh-copy-id can't work here: the DGX has password auth off. Instead, on the
#    DGX, append the key to ~/.ssh/authorized_keys, limited to the private network
#    and with no forwarding or pty:
#      from="192.168.100.0/24",restrict ssh-ed25519 AAAA... voiceprofile-backup
ssh -i ~/.ssh/voiceprofile_backup cato-user@<DGX_HOST> 'echo ok'   # test

# 2. Install the units (set DGX_HOST in the .service first; keep
#    DGX_DIR=/data/backups/voiceprofile, not the DGX's root disk)
sudo cp deploy/voiceprofile-backup.service /etc/systemd/system/
sudo cp deploy/voiceprofile-backup.timer   /etc/systemd/system/
sudoedit /etc/systemd/system/voiceprofile-backup.service   # set DGX_HOST
sudo systemctl daemon-reload

# 3. Run once now and verify end-to-end
sudo systemctl start voiceprofile-backup.service
journalctl -u voiceprofile-backup.service -n 30 --no-pager
ls -lh /home/cato-user/backups/voiceprofile/
ssh -i ~/.ssh/voiceprofile_backup cato-user@<DGX_HOST> 'ls -lh /data/backups/voiceprofile/'

# 4. Enable the nightly timer
sudo systemctl enable --now voiceprofile-backup.timer
systemctl list-timers voiceprofile-backup.timer

# 5. Failure alerts (healthchecks.io, free). In their dashboard: add a check
#    "voiceprofile backup", Period 1 day, Grace 4 hours, notify by email. Copy its
#    ping URL into the app's .env (keep it private: whoever has it can fake "OK"):
#      HEALTHCHECK_URL=https://hc-ping.com/<uuid>
sudo systemctl start voiceprofile-backup.service
journalctl -u voiceprofile-backup.service -n 5 --no-pager   # no "ping failed" warning
#    the check turns green in the dashboard. Then prove the alert reaches you:
curl -fsS https://hc-ping.com/<uuid>/1    # same URL as in .env, plus /1 -> email
sudo systemctl start voiceprofile-backup.service             # back to green
```

#### Restore procedure (test it once, before you need it)

The app's DB role lacks `CREATEDB`, so scratch-restore drills run as the
`postgres` superuser (peer auth, no password). The dump must be somewhere
`postgres` can read (e.g. `/tmp`).

```bash
# Restore into a SCRATCH database first, to confirm the dump is good:
DUMP="$(ls -t /home/cato-user/backups/voiceprofile/*.dump | head -1)"
cp "$DUMP" /tmp/restore_test.dump
sudo -u postgres createdb voiceprofile_restore_test
sudo -u postgres pg_restore --no-owner --no-privileges -d voiceprofile_restore_test /tmp/restore_test.dump
sudo -u postgres psql -d voiceprofile_restore_test -c '\dt'   # expect profiles, reviews, otp_codes
sudo -u postgres dropdb voiceprofile_restore_test
rm /tmp/restore_test.dump

# Real recovery (DESTRUCTIVE — overwrites current data):
sudo systemctl stop voiceprofile                 # stop writes
sudo -u postgres pg_restore --clean --if-exists --no-owner --no-privileges \
  -d voiceprofile /tmp/<dump-file>               # adjust DB name if not "voiceprofile"
sudo systemctl start voiceprofile
```

Confirmed working: a scratch restore of the first nightly dump brought back
`profiles`, `reviews`, and `otp_codes`.

#### Rebuilding from an empty database

The migration history now starts with a clean initial migration that creates the
base tables, so a brand-new empty DB builds with just:

```bash
flask db upgrade      # builds profiles + reviews + otp_codes from empty
```

No `init-db` / `stamp` dance is needed. Restoring a `pg_dump` also rebuilds
everything (the dump contains the full schema).

### Migration reconciliation ✅

During the server cutover we discovered the app server's database was on a
*different* migration lineage than the branch: a single squashed
`initial_migration` created directly on the box, while the laptop carried a
4-step incremental chain ending in `add profile.locale`. They diverged because
`migrations/` had been gitignored on both machines, so neither shared history.
The laptop chain's `locale` column doesn't even exist in `main`'s model — it was
i18n-era drift.

With no production data worth keeping, we reset to **one clean history** instead
of splicing the two:

- New `e5c9a1f3b207_initial_schema.py` — a squashed baseline creating `profiles`
  + `reviews` from empty (matches `main`'s models; no `locale`).
- `b7e2a91c4f08_add_otp_codes.py` re-pointed onto it (`down_revision =
  e5c9a1f3b207`).
- Deleted the 4 divergent laptop migrations.

Verified offline (no DB touched): single head `b7e2a91c4f08`; `base → head` DDL
creates `profiles`, `reviews`, `otp_codes` with their indexes.

**Cutover impact:** the server DB is dropped and recreated empty, then
`flask db upgrade` builds the clean schema. (When `feat/i18n` merges later, its
`locale` change returns properly as a new migration on top of this baseline.)

### SMS OTP delivery (Twilio) ✅

OTP codes are now sent by SMS via Twilio, not just logged — using the delivery
seam left in `services/otp_service.py`.

- `_deliver_code(phone, code)`: sends via Twilio when configured, else logs the
  code (local dev / not-yet-configured). A Twilio failure raises `OTPError`,
  which the login route already turns into a friendly "couldn't send" flash.
- **Config** (`.env`): set all three to enable SMS; leave any unset to fall
  back to logging.
  ```
  TWILIO_ACCOUNT_SID=ACxxxxxxxx
  TWILIO_AUTH_TOKEN=xxxxxxxx
  TWILIO_FROM_NUMBER=+1xxxxxxxxxx      # a from-number, OR a Messaging Service SID (MGxxxx)
  ```
  `_deliver_code` routes an `MG…` value via `messaging_service_sid` and anything
  else via `from_`, so switching to a Messaging Service is an `.env` change only.
- **Pause sends without touching creds:** `OTP_DELIVERY=log` forces logging even
  with Twilio configured (read codes from journald); `OTP_DELIVERY=auto`
  (default) sends via Twilio when configured. Handy while a 10DLC campaign is
  pending or for testing.
- `twilio==9.11.0` added to requirements.

**US A2P 10DLC:** sending from a US 10-digit number to US numbers requires 10DLC
registration (Brand + Campaign, use case 2FA/OTP) with the number attached to a
Messaging Service — otherwise carriers block it as "unregistered number". Once
the Messaging Service is approved, set `TWILIO_FROM_NUMBER` to its `MG…` SID.

**Phone format — must be E.164.** Twilio rejects local/punctuated input. Now
handled by server-side normalization at login (see "Phone number normalization"
below).

Verified: delivery unit tests pass (fallback logs without sending; configured
path calls `messages.create` with the right `to`/`from_`/`body`; a Twilio error
becomes `OTPError`).

### SMS consent / opt-in (A2P 10DLC) ✅

Carriers require a recorded opt-in before sending A2P SMS. Added a consent flow
at the point of phone collection:

- **Login page**: a required, unchecked consent checkbox with a short disclosure
  (verification codes, msg/data rates) and links to Terms and Privacy Policy. The
  fuller CTIA details (message frequency, Reply STOP/HELP) live in the linked
  Terms page ("SMS / Text Messaging" section).
- **Server enforcement** (`auth/routes.py`): `login()` won't send an SMS unless
  `sms_consent` is checked; the opt-in timestamp is captured in the session and
  written to `profiles.sms_consent_at` when the profile is created/looked up in
  `verify()`.
- **Proof of consent**: new `sms_consent_at` column (migration `c3f81a92d5e0`).
- **Public legal pages**: `/terms` and `/privacy` (unauthenticated), linked from
  the opt-in and referenced in the 10DLC campaign registration. They ship as
  **placeholders** carrying the carrier-required SMS clauses (esp. "we don't
  sell/share numbers for marketing") — finalize the legal content + contact
  details before submitting.

Deploy: `flask db upgrade` applies `sms_consent_at`. For the 10DLC campaign, use
`https://tryout.sharegud.com/terms` and `/privacy` as the opt-in/privacy URLs,
and screenshot the login checkbox as the opt-in proof.

Verified: consent flow tests pass (legal pages public; checkbox required
server-side; no SMS without consent; consent recorded to session + DB path).

### Phone number normalization ✅

Real users type numbers naturally (`(650) 253-0000`, `650 253 0000`, a leading
national `0`), but Twilio only accepts E.164 (`+16502530000`). Without cleanup
those inputs fail at the SMS step and look like "SMS is broken".

- `services/phone.py::normalize_phone` uses Google's libphonenumber
  (`phonenumbers`) to parse, validate, and format to E.164 — stripping
  punctuation and handling trunk-zero / `+` prefixes.
- `login()` normalizes before consent/send; invalid input gets a clear "that
  doesn't look like a valid phone number" message and never reaches Twilio (no
  wasted SMS).
- **Default region = `US`** (`PHONE_DEFAULT_REGION`, configurable). The MVP
  launches in the US, so a bare national number is read as US; explicit
  `+<country>` still works for international numbers. Change the env var to `RO`
  (etc.) as the user base shifts — no code change.
- `phonenumbers==9.0.37` added to requirements.

Verified: unit + route tests pass (US variants collapse to one E.164; explicit
`+CC` kept; garbage rejected before send; punctuated input normalized into
`send_code`).

### OTP send rate limiting ✅

`/auth/login` (send) had no limit — a public endpoint where each request costs
a paid SMS, so someone could bomb a victim's number and burn budget. (Verify
brute-force was already covered by the per-code 5-attempt limit.)

- `services/rate_limit.py::check_otp_rate_limit(phone, ip)` — Postgres-backed
  (no new infra; holds across the 3 gunicorn workers) via the `otp_requests`
  table (migration `d4a7f2c9b810`). Three guards: a per-phone cooldown, a
  per-phone hourly cap, and a per-IP hourly cap. Self-prunes rows past the
  window. Returns a friendly flash reason when blocked; nothing is sent.
- `login()` calls it after consent, before `send_code` (IP is the real client
  via ProxyFix).
- Tunable via env (defaults): `OTP_RESEND_COOLDOWN_SECONDS=60`,
  `OTP_MAX_PER_PHONE_PER_HOUR=5`, `OTP_MAX_PER_IP_PER_HOUR=20`.

Best-effort under high concurrency (no row lock) — fine for a pilot. Verified:
cooldown, per-phone cap, per-IP cap, and stale-row pruning all pass (isolated
SQLite).

### Admin login (Google OIDC) ✅ (follow-ups open)

Admin area with Google sign-in (see "Admin login (Google OIDC)" under Concepts):
`admin_users` + `admin_identities` (migration `d213e5e9336f`), `ADMIN_EMAILS`
break-glass allowlist, `flask add-admin|enable-admin|disable-admin|list-admins`.
Mounted at `ADMIN_URL_PREFIX` (set per host; the real path is deliberately not
written in this public repo — `<prefix>` below). Live on laptop, lab and
production since 2026-10-14; real Google login verified on lab and production,
`/admin/` returns 404 where a custom prefix is set.

#### Follow-up A — Cloudflare Access in front of the admin path (not done)

A second, independent gate: Cloudflare asks for an emailed one-time PIN before
any request under `<prefix>` reaches Flask, so the admin area is invisible to
the internet even if the app had a bug. Free on the Zero Trust plan, no code
change. It can't be bypassed because the origin is only reachable through the
tunnel (gunicorn on `127.0.0.1:5001`, port not publicly bound).

1. Cloudflare dashboard → **Zero Trust → Access → Applications → Add an
   application → Self-hosted**. Name `VoiceProfile admin`; session duration
   e.g. 24h.
2. **Destination:** domain `tryout.sharegud.com`, path `<prefix>` (no leading
   slash; covers everything under it, including the Google callback
   `<prefix>/auth` — the browser already holds the Access cookie by then).
3. **Policy:** action *Allow*, include → *Emails* → the admin addresses.
   Login method *One-time PIN* (default), or add Google as an Access identity
   provider.
4. **Verify:**
   - `curl -sI https://tryout.sharegud.com/<prefix>/` → `302` to
     `https://<team>.cloudflareaccess.com/...` (not to `<prefix>/login`)
   - `curl -s https://tryout.sharegud.com/healthz` → ok (worker paths untouched)
   - browser: PIN email → Google sign-in → dashboard.

Trade-off: admin emails then live in two places (`ADMIN_EMAILS`/`admin_users`
**and** the Access policy) — adding an admin means updating both. Optional
later hardening: verify the `Cf-Access-Jwt-Assertion` header in Flask.

#### Follow-up B — non-OAuth callback errors return 500, not 403 (minor)

`blueprints/admin/routes.py` `auth()` catches only `OAuthError` around
`authorize_access_token()`. Two other failure classes escape as a 500:

- `authlib.jose` errors (`JoseError`, e.g. `InvalidClaimError`) from ID-token
  validation — nonce mismatch, or clock skew past Authlib's leeway. `JoseError`
  is **not** an `OAuthError` subclass.
- Network errors (`requests.RequestException`) calling Google's token or JWKS
  endpoint.

Fails closed (no session is set) — the only harm is a 500 page and a traceback
in the journal. Fix: catch `authlib.common.errors.AuthlibBaseError` (base of
both `OAuthError` and `JoseError`) plus `requests.RequestException`, log the
class name, render `not_authorized.html` with 403; add one test per class.

#### Follow-up C — dev-login loopback check trusts `X-Forwarded-For` (minor)

`login()` grants the no-Google dev session when `current_app.debug` and
`request.remote_addr` is loopback. With `ProxyFix(x_for=1)`, `remote_addr` is
taken from the last `X-Forwarded-For` value sent by *whoever connects*, so with
`FLASK_DEBUG=1` **and** the app bound to a non-loopback interface (e.g.
`flask run --host 0.0.0.0` on a LAN), a LAN client sending
`X-Forwarded-For: 127.0.0.1` gets admin without Google.

Not reachable on lab or production (`FLASK_DEBUG=0`, gunicorn on loopback,
Cloudflare supplies the real client IP). Until fixed: never combine
`FLASK_DEBUG=1` with a non-loopback `--host`. Fix: also require the direct
socket peer to be loopback —
`request.environ.get("werkzeug.proxy_fix.orig", {}).get("REMOTE_ADDR", request.remote_addr)`
— plus a test that a spoofed header from a non-loopback peer gets the Google
redirect.

### Raw voice recordings ✅ (follow-ups open)

The audio of every onboarding **story** / **availability** take is kept in
`voice_recordings` (migration `e7b3c5d18a42`, deferred `bytea`), for debugging and for
building Whisper / extraction test cases. Admin-only; the worker never sees them.

Env keys (per host; all optional):

- `VOICE_RECORDING_CAPTURE=1` — turn saving on. **Default off**: nothing is stored until set.
- `VOICE_RECORDING_MAX_BYTES` — larger takes aren't saved (default 25 MB; a 3-minute take is ~1–3 MB).
- `ADMIN_TIMEZONE` — IANA zone (e.g. `America/Los_Angeles`) for admin date filters and
  displayed times; blank → UTC; an unknown name logs a startup warning and uses UTC.

Capture is best-effort: a storage failure is logged and the worker's onboarding continues
unchanged. Takes Whisper failed on are kept with the error. Browse at `<prefix>/recordings`
(phone / date / step / decision filters, newest first, in-browser playback). The log records
each time a browser fetches a take from the server, not every play: Firefox replays from its
own media cache despite `no-store`, so a replay in the same window may leave no log line.
Chrome's recorder writes a zero WebM Duration; playback and export fill it in from
`duration_ms` (stored audio is unchanged).

CLI (run on the host that holds the DB):

- `flask recordings export OUT_DIR [--phone] [--from] [--to] [--step] [--accepted-only]` —
  audio files + `manifest.jsonl` (per take, incl. `final_text`) + `profiles.jsonl`
  (reviewed `profile_data` for completed profiles).
- `flask recordings delete (--phone N | --id N | --before YYYY-MM-DD) [--yes]`
- `flask profile delete (--phone N | --id N) [--yes]` — removes the profile, its reviews,
  recordings and the phone's OTP rows; use this for "delete my data" requests.

**Exports contain real voices and phone numbers and this repo is public — never commit
one.** Write them under `exports/` (gitignored) or outside the repo; copy to the laptop
with `scp`.

Rollout per host: pull, `flask db upgrade`, set the env keys, restart.

#### Follow-ups (open, all minor)

Found in the final review and the manual trial; none blocks rollout.

- **R1 — decision can land on an older take.** `mark_decision` marks the newest
  *undecided* take of the step. If the newest take was never saved (over the size cap, or
  a DB error), the worker's Continue/Confirm and edited text go onto their previous take,
  so an export pairs older audio with newer `final_text`. Fix: return the take id from
  `/transcribe`, send it back with `/confirm`, and mark that take.
- **R2 — huge `?page=` → 500.** `?page=1e20` overflows in the paginate query (admin-only,
  self-inflicted). Fix: clamp `page` to a sane maximum (the profiles page already does,
  via `_page_number` in `blueprints/admin/routes.py`; reuse it).
- **R3 — unexpected query keys → 500.** The recordings page passes every query argument
  back into `url_for` for the paging links, so `?endpoint=x` (or `_external`, `_anchor`)
  raises `TypeError`. Fix: carry over only `phone`, `from`, `to`, `step`, `decision`.
- **R4 — export files readable by every user on the host.** `flask recordings export`
  creates files with the default umask (`644`/`755`). Fix: create the directory `0700` and
  the files `0600`.
- **R5 — whole-file reads.** `save_take` reads the full upload before checking
  `VOICE_RECORDING_MAX_BYTES` (Flask sets no `MAX_CONTENT_LENGTH`, so only Cloudflare's
  request limit bounds it), and the audio endpoint loads the whole blob from Postgres for
  every Range request (each seek). Fine at pilot volumes. Fix: check `request.content_length`
  first / read in a bounded way; serve ranges with `substring(audio ...)` in SQL.
- **R6 — a resend after a Whisper failure is stored twice.** Resubmitting the same audio
  after a 502 saves it again as a new attempt. Fix: skip a take whose SHA-256 matches the
  previous take of the same step.
- **R7 — `recordings delete` count can differ from what is deleted.** The confirmation
  counts the matching takes, then the delete runs its own query, so takes arriving in
  between are also removed (the printed "Deleted N" is accurate). Fix: delete exactly the
  ids that were counted.
- **R8 — DB errors elsewhere can log worker text.** SQLAlchemy error messages include the
  values being written. The recording code logs only the exception class, but other code
  paths (profile saves, reviews) still log full errors. Fix: set
  `SQLALCHEMY_ENGINE_OPTIONS = {"hide_parameters": True}` app-wide; cost: harder debugging
  of genuine DB errors.
- **R9 — older code logs transcript / profile text on failures (predates recordings).**
  `services/stt_service.py` logs up to 1000 chars of an unexpected Whisper payload;
  `services/nlp_service.py` puts the first 200 chars of an unparseable LLM reply into
  `ExtractionError`, which onboarding logs and stores in `profile_data`. Fix: log lengths
  and error classes only.

### Admin profiles page ✅

`<prefix>/profiles` (linked from the dashboard) lists every worker profile with admin
details only: id, name, phone, status, review / recording counts, photo yes/no, created and
last-change times. It never shows the job, availability, transcripts or review text (the
query selects only those columns).

- **Counts** (always whole-database): total, completed, incomplete (by the step they
  stopped at, `name_confirm` counted as name, plus how many hit an extraction error), and
  with reviews. "Completed" = onboarding reached `completed`.
- **Search "Name or phone":** input made only of digits and phone formatting
  (`+ ( ) - space`) matches those digits anywhere in the phone number (any length, so `555`
  works); anything with a letter is a case-insensitive "name contains". Filters: status
  (completed / incomplete) and reviews (has / none). 50 per page, newest first.
- **Delete…** opens a confirmation page listing what goes (reviews, recordings + size,
  the phone's OTP rows) and asks for the phone's last 4 digits, or the profile ID when there
  is no phone. Same deletion as `flask profile delete`. The log line has ids and counts only
  (no name or phone). Copies in backups age out within 14 days.
- **Times** show in `ADMIN_TIMEZONE`; the filter row shows the zone and the current time
  there (as of page load). Profile and review timestamps are naive columns filled by the
  database's `now()`, i.e. in the Postgres server's `TimeZone` setting (the laptop's is
  America/Los_Angeles), so the page reads `SHOW TimeZone` to convert them. Recording times
  are `timestamptz` and unaffected.

Rollout per host: pull, restart. No migration, no new env keys or dependencies.

### DGX exposure incident + service hardening (2026-10-25) ✅ (rolled out 2026-10-27)

**What happened.** Prod onboarding showed "Couldn't turn that into text" on every
recording. Whisper was returning a bare 500 because the DGX's `/` was full, and it
writes each upload to `/tmp` first. The disk had filled because Ollama ran with
`OLLAMA_HOST=0.0.0.0` and no auth on a box with a public IP. Its log showed `/api/pull`
calls from many public IPs, and two models that weren't ours. One of them,
`sysverify-63970`, was a renamed copy of our qwen2.5:32b (same blob), apparently a
write probe. Whisper (`:6000`, had live connections from public IPs) and vLLM (`:8000`, `api_key=None`) were open
the same way. This section's earlier text claimed the DGX was "never internet-exposed".

Separately, **vLLM had been down since 2026-10-21 15:43 UTC**. Whisper, containerd and
Ollama restarted around the same time. When vLLM's restart came, `:8000` was still
held, so the bind failed with "Address already in use". systemd gave up after 3
tries, and extraction failed for every worker until the 25th.

**Containment (done on the box, 2026-10-25):**
- **Firewall.** ufw is on: deny incoming, allow SSH, allow `192.168.100.0/24`.
  Checked from outside: 6000, 8000 and 11434 are filtered.
- **Ollama** is stopped and disabled; prod uses vLLM. Its log is saved to
  `~/ollama-incident-2026-10-25.log` on the DGX. Foreign models were removed (only
  `mistral:7b-instruct` remains), and the pip cache was cleared. `/` is at 50%.
- **Compromise check came back clean.** Ollama is 0.32.6. Crontabs are clean and
  there are no odd processes. `authorized_keys` holds only our keys, password auth
  is off, there are no root keys, and the only accepted logins are ours.
- **vLLM** was restarted (after ufw), and the app server reaches it again.
- **Off-box backups were fixed.** They had failed every night with
  `Permission denied (publickey)`: the backup key had never been authorized,
  because `ssh-copy-id` can't work with password auth off. Separately, the installed
  unit's `DGX_DIR` had drifted to the root disk. The key was added by hand (see
  Section 5) and `DGX_DIR` restored to `/data/backups/voiceprofile`. Verified
  2026-10-25 11:53.

**Code (branch `fix/dgx-hardening`).** The firewall is no longer the only layer:
- **Whisper requires its API key.** `whisper_service/app.py` checks `X-API-Key`
  against `WHISPER_API_KEY` (read from `/etc/whisper.env`) and refuses to start
  without it. The check is a middleware, so a stranger's upload is rejected before
  it's read or written to disk.
- **Whisper failures say why.** A failed upload or transcription returns a JSON
  500 with the reason (e.g. `OSError: [Errno 28] No space left on device`) and
  leaves no temp file behind. `services/stt_service.py` logs Whisper's status and
  body, or the connection error. The browser still gets a generic message.
- **vLLM requires a key.** The app sends `LLM_API_KEY` (new setting, default
  `"ollama"` so lab and dev are unchanged). vLLM reads `VLLM_API_KEY` from
  `/etc/vllm-qwen.env`, so it isn't visible in `ps`. vLLM 0.6.3 checks it only on
  `/v1/*`; `/health`, `/metrics` and `/tokenize` stay open, which is why the
  private bind matters.
- **Both units bind `192.168.100.2`**, not `0.0.0.0`. Nothing on the DGX calls them
  via localhost (checked). The rollout found that vLLM 0.6.3 ignores `--host`;
  see "vLLM bind guard" below.
- **Backup alerts.** `deploy/backup_db.sh` reports every run's exit status to
  healthchecks.io when `HEALTHCHECK_URL` is set in `.env` (Section 5, step 5).
  Without it, behaviour is unchanged.
- **Whisper deploys from a checkout.** Until now the DGX ran a hand-copied
  `~/whisper_service/app.py` with no git checkout. The unit now runs
  `~/VoiceProfile/whisper_service` (a clone) with the existing venv at
  `~/whisper_service/venv`.

#### Rollout (in this order, so nothing breaks partway)

```bash
# 1. App server: new key, then the code. vLLM ignores keys until step 3.
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'   # new LLM_API_KEY
#    add LLM_API_KEY=<value> to .env
git pull && sudo systemctl restart voiceprofile

# 2. DGX, Whisper
cd ~ && git clone https://github.com/val75/VoiceProfile.git      # public repo
sudo install -m 600 -o root -g root /dev/null /etc/whisper.env
sudoedit /etc/whisper.env        # WHISPER_API_KEY=<the app's existing value; if the app's
                                 #   .env has none, add one there first and restart the app>
systemctl cat whisper > ~/whisper.service.pre-hardening          # rollback copy
sudo cp ~/VoiceProfile/whisper_service/whisper.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl restart whisper
ss -ltnp | grep 6000             # 192.168.100.2:6000
#    from the app server: curl without the key -> 401; then record in the app -> 200
#    once good: mv ~/whisper_service/app.py ~/whisper_service/app.py.retired

# 3. DGX, vLLM (a few minutes' extraction outage while the model reloads)
systemctl cat vllm-qwen > ~/vllm-qwen.service.pre-hardening
diff <(tail -n +2 ~/vllm-qwen.service.pre-hardening) ~/VoiceProfile/deploy/vllm-qwen.service
#    expect only the key + host changes; carry over any box-specific values
#    (CUDA_VISIBLE_DEVICES, HF_HOME) before installing
sudo install -m 600 -o root -g root /dev/null /etc/vllm-qwen.env
sudoedit /etc/vllm-qwen.env      # VLLM_API_KEY=<same value as the app's LLM_API_KEY>
bash ~/VoiceProfile/deploy/patch-vllm-bind.sh                    # else --host is ignored
sudo cp ~/VoiceProfile/deploy/vllm-qwen.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl restart vllm-qwen
journalctl -u vllm-qwen -f       # "Uvicorn running on socket ('192.168.100.2', 8000)"
ss -ltnp | grep ':8000'          # 192.168.100.2:8000, never 0.0.0.0:8000
#    from the app server: curl http://192.168.100.2:8000/v1/models -> 401;
#    with -H "Authorization: Bearer <key>" -> 200; then finish an onboarding

# 4. App server: backup alerts. Section 5, step 5 (healthchecks.io check + .env).
```

Rollback: put back the saved `*.pre-hardening` unit, then `daemon-reload` and restart.
If Ollama is ever re-enabled on the DGX, set `OLLAMA_HOST=127.0.0.1:11434`.

### vLLM bind guard + uptime check (2026-10-27) ✅ (rolled out 2026-10-28)

**vLLM 0.6.3.post1 ignores `--host`.** The rollout above showed vLLM on
`0.0.0.0:8000` although its args said `host='192.168.100.2'`. In 0.6.3.post1,
`run_server()` opens the port itself with `sock.bind(("", args.port))`, i.e. every
interface, and hands the socket to uvicorn, so `--host` never takes effect (and
the log reads "running on socket (...)"). vLLM 0.6.4 fixed it; we can't upgrade
(Volta pin). ufw and the key still covered the gap.
- **`deploy/patch-vllm-bind.sh`** applies 0.6.4's one-line fix,
  `sock.bind((args.host or "", args.port))`, to `~/vllm-venv`. Re-running it is
  harmless. `build-vllm-venv.sh` runs it, so a rebuild stays patched.
- **`deploy/vllm-qwen.service` refuses to start** without the fix: an
  `ExecStartPre` runs `patch-vllm-bind.sh --check` (from the `~/VoiceProfile`
  clone), so a reinstall fails loudly instead of quietly listening on the public
  IP again. The journal then says to run the patch script.
- The DGX venv was patched by hand on 2026-10-27, so the script finds it already done.
- 0.6.4 also sets `SO_REUSEADDR` on that socket, and 0.6.3 doesn't. That may explain
  the 2026-10-21 "Address already in use" (unverified; not patched).

**vLLM uptime check.** `deploy/vllm_probe.sh` runs every 5 minutes on the app
server (`vllm-probe.timer`). It lists models at `LLM_URL` with the app's
`LLM_API_KEY` and checks `LLM_MODEL` is served: the same path, key and model the
app's extraction needs. Healthy runs send a healthchecks.io success ping. Failed
runs send a "log" ping with the reason, which shows in the check's Events but
doesn't change its status. With Period 6 min and Grace 9 min (the Period is a
minute longer than the timer, so a slightly late healthy probe doesn't count as
late), the check turns amber 6 minutes after the last good probe and red, with
the email, after 15. A planned restart stays quiet if vLLM is serving again
within about 10 minutes (the 2026-10-27 restart took about 80 s); a longer one alerts.

#### Rollout

```bash
# 1. DGX: install the guarded unit (vLLM keeps running; it applies on the next start)
cd ~/VoiceProfile && git pull
bash deploy/patch-vllm-bind.sh --check           # expect "OK: ... binds --host"
systemctl cat vllm-qwen > ~/vllm-qwen.service.pre-guard           # rollback copy
diff <(tail -n +2 ~/vllm-qwen.service.pre-guard) deploy/vllm-qwen.service
#    expect only the guard (ExecStartPre ... --check) and comment changes; carry
#    over any box-specific values (CUDA_VISIBLE_DEVICES, HF_HOME) before installing
sudo cp deploy/vllm-qwen.service /etc/systemd/system/ && sudo systemctl daemon-reload

# 2. healthchecks.io: add a check "vllm", Period 6 minutes, Grace 9 minutes,
#    notify by email. App server .env: VLLM_HEALTHCHECK_URL=https://hc-ping.com/<uuid>

# 3. App server: install the probe
cd /home/cato-user/VoiceProfile && git pull
sudo cp deploy/vllm-probe.service deploy/vllm-probe.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start vllm-probe.service
journalctl -u vllm-probe.service -n 5 --no-pager # "[vllm-probe] OK: qwen2.5-32b at ..."
#    the check turns green in the dashboard
sudo systemctl enable --now vllm-probe.timer
systemctl list-timers vllm-probe.timer
```

Rollback (DGX): put back `~/vllm-qwen.service.pre-guard`, then `daemon-reload`.

### Whisper uptime check (2026-10-28) ✅ (rolled out 2026-10-28)

`deploy/whisper_probe.sh` is the vLLM probe's twin for Whisper, every 5 minutes on
the app server (`whisper-probe.timer`). Whisper has no health endpoint, so the
probe sends a generated silent clip to `WHISPER_URL` the way the app sends audio
(the app's `WHISPER_API_KEY`, a `file` form field, the app's 90 s timeout) and
expects a transcript back. A real clip, not an empty request, so the model and the
temp files are exercised too. The clip is about 1.1 MB, just over the 1 MiB that
Starlette keeps in memory, so it is written to `/tmp` like a big recording. A
disk too full for that, as on 2026-10-25, counts as down. A disk with a few MB
left still passes, so this is no substitute for watching DGX disk space. Whisper
works in 30 s windows, so a run costs about the same GPU time as a 1 s clip.
Whisper handles one request at a time, so a probe can queue behind a worker's
recording; a timeout is logged as "no response" (hung model or GPU), not "cannot
reach" (network). Same reporting as the vLLM probe: success
pings when healthy; when not, a "log" ping with the reason, including Whisper's
own error text (e.g. `HTTP 500: ... No space left on device`), with no status change.
Period 6 min, Grace 9 min: the email comes 15 minutes after the last good probe.

#### Rollout (app server)

```bash
# 1. healthchecks.io: add a check "whisper", Period 6 minutes, Grace 9 minutes,
#    notify by email. App server .env: WHISPER_HEALTHCHECK_URL=https://hc-ping.com/<uuid>

# 2. Install the probe
cd /home/cato-user/VoiceProfile && git pull
sudo cp deploy/whisper-probe.service deploy/whisper-probe.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start whisper-probe.service
journalctl -u whisper-probe.service -n 5 --no-pager  # "[whisper-probe] OK: transcribed a test clip at ..."
#    the check turns green in the dashboard
sudo systemctl enable --now whisper-probe.timer
systemctl list-timers whisper-probe.timer
```

To turn a probe off (Whisper or vLLM): pause its check in healthchecks.io first,
so the missing pings don't email, then `sudo systemctl disable --now
whisper-probe.timer` (or `vllm-probe.timer`).

---

## Open items

- [x] **Section 3** — systemd unit built (`deploy/voiceprofile.service`) +
  cutover runbook written. **Server cutover still to be run on the box.**
- [x] **Section 4** — OTP → Postgres (hashed, attempt-limited), `SECRET_KEY`
  fail-loud, cookie hardening, `ProxyFix`, `/healthz`, workers bumped to 3.
- [x] **Section 5** — nightly `pg_dump` backups (systemd timer) copied off-box
  to the DGX, retention + restore procedure documented; from-scratch bootstrap
  note added.

### Remaining

- [x] **Server cutover** — done. Production runs gunicorn under systemd
  (`voiceprofile.service`, enabled) behind the tunnel; DB was nuked and rebuilt
  from the clean initial migration; `/healthz` + the public site verified.
- [x] **Backup setup** — done. `voiceprofile-backup.timer` runs nightly;
  `pg_dump` copied off-box to the DGX at `/data/backups/voiceprofile`. The off-box
  copy silently failed for weeks until 2026-10-25 (see "DGX exposure incident").
- [ ] **Test restore** — restore the latest dump into a scratch DB once to prove
  recovery (commands under Section 5 → Restore procedure).
- [ ] **Merge to `main`** — fold `chore/production-deploy` into `main` so
  production tracks `main` again, then `git checkout main && git pull` on the box.
- [ ] **Cloudflare Access on the admin path** — Admin login, Follow-up A.
- [ ] **Admin callback: non-OAuth errors → 403** — Admin login, Follow-up B.
- [ ] **Dev-login loopback check vs. `X-Forwarded-For`** — Admin login,
  Follow-up C.
- [ ] **Raw voice recordings follow-ups R1–R9** — minor; R1 (decision on the wrong take)
  and R4 (export file permissions) first.
- [x] **DGX hardening rollout** — done 2026-10-27 (runbook under "DGX exposure incident").
- [x] **vLLM bind guard + uptime check** — done 2026-10-28; probe green.
- [x] **Whisper uptime check** — done 2026-10-28; probe green.
- [ ] **Same exposure check on the lab box and the app server**:
  `sudo ss -ltnp` (anything on `0.0.0.0` / `*` besides SSH?) and `sudo ufw status`.
- [x] **Backup failure alert** — done; healthchecks.io check live, alert email
  verified 2026-10-27 (Section 5, step 5).
- [ ] **Hourly `ssh-rsa` rejects on the DGX** at :30:13 (`ssh-rsa not in
  PubkeyAcceptedAlgorithms`) — find the source.
- [ ] **The 2026-10-21 restart** — why Whisper, containerd, Ollama and vLLM all
  restarted, and what held `:8000`. Candidate: vLLM 0.6.3 binds without
  `SO_REUSEADDR`, so leftover TIME_WAIT connections block a quick rebind.
- [ ] **DGX `/` headroom** — `/` is a 98 GB LV; check `sudo vgs` for free space to grow it.
  No disk-space alert yet: the Whisper probe only fails once `/` can't take a
  1 MB write.

### Resolved during setup

- Public-IP exposure closed: app moved to loopback, `cloudflared` ingress
  repointed to `127.0.0.1:5001`, port 5001 no longer publicly bound.
- Cloudflare tunnel bug fixed: `config.yml` and DNS now point at one
  consolidated tunnel/UUID (a mismatch had caused a 502, then an NXDOMAIN).
- Confirmed `FLASK_DEBUG=0` in production (`=1` only on the laptop) — the
  interactive debugger is not exposed to the internet.
