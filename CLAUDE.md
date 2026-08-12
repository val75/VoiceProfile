# VoiceProfile

## Purpose

Workers with limited literacy or typing ability **speak** into their phone browser to build a professional profile. Pipeline: voice → Whisper transcription → LLM extraction of structured data (work experience, availability) → worker reviews/edits → shareable profile with a QR code others can scan to leave reviews.

- **Auth:** passwordless, phone number + OTP.
- **Onboarding:** a voice state machine — `intro → name → name_confirm → story → availability → review → completed`. Each step records audio, transcribes it, and lets the worker confirm/edit before advancing.
- **STT:** self-hosted Whisper API (`whisper_service/`, FastAPI + openai-whisper, runs on the DGX).
- **Extraction:** local LLM via Ollama through the OpenAI SDK (`services/nlp_service.py`) — returns structured JSON (`work_experience[]`, `summary`, `availability`).
- **Reviews:** owner gets a QR code linking to a public profile (`/p/<id>`) where anyone can leave a typed or voice review.

## Tech Stack

- **Backend:** Flask 2.0+, Python 3.9+
- **Database:** PostgreSQL with JSONB columns, SQLAlchemy ORM, Alembic migrations
- **STT:** Self-hosted Whisper API (vendored in `whisper_service/`)
- **LLM:** Local Ollama (default `mistral:7b-instruct`) via OpenAI SDK
- **Frontend:** Vanilla JS (ES6 classes), plain CSS, Web Audio API
- **Serving:** gunicorn behind a Cloudflare Tunnel (see `deploy/`)

## Project Structure

```
app.py                    # Flask app factory, blueprint registration, healthz
config.py                 # Config from environment variables
models/
  profile.py              # WorkerProfile (JSONB profile_data & transcripts, photo)
  otp.py                  # OTP codes for phone auth
  review.py               # Reviews left on a public profile
services/
  stt_service.py          # Whisper API integration
  nlp_service.py          # LLM profile-data extraction (Ollama/OpenAI SDK)
  otp_service.py          # OTP send/verify
whisper_service/          # Self-hosted Whisper backend (FastAPI, runs on DGX)
blueprints/
  auth/                   # Phone + OTP login (no URL prefix)
  onboarding/             # Voice onboarding state machine (/onboarding)
  profiles/               # Profile view + QR code (/profiles)
  reviews/                # Public profile + QR review submission (/p)
  voice_input/            # Standalone voice record & transcribe (/voice)
  profile_builder/        # Text-to-structured-data parsing (/builder)
```

## Running

```bash
flask run
```

Requires `.env` with `DATABASE_URL`, `WHISPER_URL`, `WHISPER_API_KEY`, `SECRET_KEY`.

## Commands

```bash
flask init-db    # Create database tables
flask reset-db   # Drop and recreate tables (debug mode only)
```

## Key Patterns

- Blueprints register under URL prefixes: `/onboarding`, `/voice`, `/profiles`, `/builder`
- Audio recording uses MediaRecorder API with format auto-detection (webm/ogg/mp4)
- Onboarding state machine tracks progress: `name → name_confirm → skills → experience → availability → review`
- JSONB columns (`profile_data`, `transcripts`) allow flexible schema evolution

## Workflow Orchestration

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (2+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 2. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer
- Challenge your own work before presenting it

## Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `tasks/todo.md`
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.
