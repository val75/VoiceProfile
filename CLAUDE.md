# VoiceProfile

Voice-based worker profile creation app. Users speak into a browser, audio is transcribed via Whisper, and structured profile data is extracted and stored.

## Tech Stack

- **Backend:** Flask 2.0+, Python 3.9+
- **Database:** PostgreSQL with JSONB columns, SQLAlchemy ORM, Alembic migrations
- **STT:** External Whisper API (self-hosted)
- **Frontend:** Vanilla JS (ES6 classes), plain CSS, Web Audio API

## Project Structure

```
app.py                  # Flask app factory, blueprint registration
config.py               # Config from environment variables
models/profile.py       # WorkerProfile model (JSONB profile_data & transcripts)
services/stt_service.py # Whisper API integration
services/nlp_service.py # Profile data extraction (stub)
blueprints/
  onboarding/           # Step-by-step voice onboarding (in progress)
  voice_input/          # Standalone voice record & transcribe
  profiles/             # Profile CRUD endpoints
  profile_builder/      # Text-to-structured-data parsing
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
