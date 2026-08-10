"""Whisper transcription API for VoiceProfile.

Runs on the DGX. VoiceProfile's services/stt_service.py POSTs audio here
(configured via WHISPER_URL) and expects {"text", "language"} back.

Deploy: see whisper_service/README.md.
"""
from fastapi import FastAPI, UploadFile, File, HTTPException
import whisper
import tempfile
import os

app = FastAPI()

model = whisper.load_model("medium")  # or "base" / "small" / "large"


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        result = model.transcribe(tmp_path)
        return {
            "text": result["text"],
            "language": result.get("language"),
        }
    finally:
        os.remove(tmp_path)
