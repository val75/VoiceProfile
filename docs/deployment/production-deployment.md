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
ssh-copy-id -i ~/.ssh/voiceprofile_backup.pub cato-user@<DGX_HOST>
ssh -i ~/.ssh/voiceprofile_backup cato-user@<DGX_HOST> 'echo ok'   # test

# 2. Install the units (set DGX_HOST in the .service first)
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
  `pg_dump` copied off-box to the DGX at `/home/cato-user/backups/voiceprofile`
  (home dir, since `/data` wasn't writable by `cato-user`). First dump verified
  on the DGX.
- [ ] **Test restore** — restore the latest dump into a scratch DB once to prove
  recovery (commands under Section 5 → Restore procedure).
- [ ] **Merge to `main`** — fold `chore/production-deploy` into `main` so
  production tracks `main` again, then `git checkout main && git pull` on the box.

### Resolved during setup

- Public-IP exposure closed: app moved to loopback, `cloudflared` ingress
  repointed to `127.0.0.1:5001`, port 5001 no longer publicly bound.
- Cloudflare tunnel bug fixed: `config.yml` and DNS now point at one
  consolidated tunnel/UUID (a mismatch had caused a 502, then an NXDOMAIN).
- Confirmed `FLASK_DEBUG=0` in production (`=1` only on the laptop) — the
  interactive debugger is not exposed to the internet.
