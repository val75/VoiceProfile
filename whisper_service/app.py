"""Whisper transcription API for VoiceProfile.

Runs on the DGX. VoiceProfile's services/stt_service.py POSTs audio here
(configured via WHISPER_URL) and expects {"text", "language"} back.

Every request must carry X-API-Key matching the WHISPER_API_KEY env var
(the same value as the app's WHISPER_API_KEY); the service won't start
without it.

Deploy: see whisper_service/README.md.
"""
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse
import whisper
import hmac
import logging
import tempfile
import os

logger = logging.getLogger("whisper_service")

API_KEY = os.environ.get("WHISPER_API_KEY")
if not API_KEY:
    raise RuntimeError("WHISPER_API_KEY is not set; refusing to run without auth")

app = FastAPI()

model = whisper.load_model("medium")  # or "base" / "small" / "large"


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    # A middleware, not a dependency: FastAPI parses (and spools to disk) the
    # upload before dependencies run, so this rejects strangers before that.
    given = request.headers.get("x-api-key", "")
    if not hmac.compare_digest(given.encode(), API_KEY.encode()):
        return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return await call_next(request)


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    fd, tmp_path = tempfile.mkstemp(suffix=".wav")
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(await file.read())
        result = model.transcribe(tmp_path)
    except Exception as e:
        # Say why (e.g. a full disk), so the app's log shows the cause.
        logger.exception("Transcription failed")
        return JSONResponse(
            status_code=500,
            content={"detail": f"transcription failed: {type(e).__name__}: {e}"},
        )
    finally:
        os.remove(tmp_path)

    return {
        "text": result["text"],
        "language": result.get("language"),
    }
