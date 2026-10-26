"""Whisper transcription API for VoiceProfile.

Runs on the DGX. VoiceProfile's services/stt_service.py POSTs audio here
(configured via WHISPER_URL) and expects {"text", "language"} back.

Every request must carry X-API-Key matching the WHISPER_API_KEY env var
(the same value as the app's WHISPER_API_KEY); the service won't start
without it.

Deploy: see whisper_service/README.md.
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
# request.form() yields Starlette's UploadFile and raises Starlette's
# HTTPException (FastAPI's is a subclass) for a malformed body.
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
import whisper
import hmac
import logging
import shutil
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
async def transcribe(request: Request):
    # The form is parsed here, not via a File(...) parameter: parsing spools
    # uploads over 1 MB to /tmp, and a full disk must hit the except below
    # (JSON 500 with the reason) rather than FastAPI's reasonless 400.
    form = None
    tmp_path = None
    try:
        form = await request.form()
        upload = form.get("file")
        if not isinstance(upload, UploadFile) or not upload.filename:
            raise HTTPException(status_code=400, detail="No file provided")

        fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        with os.fdopen(fd, "wb") as tmp:
            shutil.copyfileobj(upload.file, tmp)
        result = model.transcribe(tmp_path)
    except StarletteHTTPException:
        raise  # 400s: no file, or a malformed body
    except Exception as e:
        # Say why (e.g. a full disk), so the app's log shows the cause.
        logger.exception("Transcription failed")
        return JSONResponse(
            status_code=500,
            content={"detail": f"transcription failed: {type(e).__name__}: {e}"},
        )
    finally:
        if tmp_path:
            os.remove(tmp_path)
        if form is not None:
            await form.close()

    return {
        "text": result["text"],
        "language": result.get("language"),
    }
