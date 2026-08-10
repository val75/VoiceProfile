# Whisper transcription service

The speech-to-text backend for VoiceProfile. A small FastAPI app that wraps
[openai-whisper](https://github.com/openai/whisper) and runs on the **DGX**
(GPU box), separate from the web app.

## How it connects to VoiceProfile

```
VoiceProfile app  ──POST /transcribe (audio)──▶  this service (DGX :6000)
(services/stt_service.py)   ◀── {"text", "language"} ──
```

VoiceProfile calls it via the `WHISPER_URL` in its `.env`, e.g.
`WHISPER_URL=http://192.168.100.2:6000/transcribe`, over the private network
between the app server and the DGX. Keep the two in sync: this service returns
`{"text", "language"}`, which `services/stt_service.py` reads as `data["text"]`.

## Requirements

- An NVIDIA GPU with a working CUDA + PyTorch install (this runs on the DGX-2).
- **ffmpeg** installed system-wide (`sudo apt install ffmpeg`) — Whisper shells
  out to it to decode audio (WebM/Ogg/mp4 from the browser, WAV, etc.).
- Python deps in `requirements.txt` (installed in a venv).

## Deploy on the DGX

```bash
# 1. Get the code (the whole VoiceProfile repo; only whisper_service/ is used here)
git clone https://github.com/val75/VoiceProfile.git
cd VoiceProfile/whisper_service

# 2. venv + deps
python3 -m venv venv
venv/bin/pip install -r requirements.txt
#    NOTE: torch must match the DGX's CUDA. If pip pulls a CPU-only or wrong-CUDA
#    build, install torch from the correct index first (see pytorch.org), then
#    the rest of requirements.txt.

# 3. Sanity-check the model loads and transcribes (first run downloads the model)
venv/bin/python - <<'PY'
import torch, whisper
print("CUDA available:", torch.cuda.is_available())
m = whisper.load_model("medium")
print(m.transcribe("some_speech.wav")["text"])
PY

# 4. Run under systemd (edit the placeholders in the unit first)
sudo cp whisper.service /etc/systemd/system/whisper.service
sudoedit /etc/systemd/system/whisper.service      # set DGX_USER, REPO, VENV
sudo systemctl daemon-reload
sudo systemctl enable --now whisper
sudo journalctl -u whisper -f                      # wait for "Application startup complete"
```

## Updating

```bash
cd VoiceProfile && git pull
sudo systemctl restart whisper
```

uvicorn does not hot-reload in production, so **always restart after a code
change** — a stale process silently running old code caused a hard-to-find
outage once (the handler returned `null` for every request).

## Notes

- **Binding.** The unit runs `--host 0.0.0.0`, which listens on every interface.
  If the DGX has a public interface, prefer `--host <private-ip>` so only the app
  server can reach it, or firewall port 6000.
- **No auth.** The endpoint doesn't check an API key today. `stt_service.py`
  sends an `X-API-Key` header that this service ignores. Fine on a trusted
  private network; add a check here if that ever changes.
- **Model size.** `whisper.load_model("medium")` — swap for `small`/`large`
  to trade accuracy for speed/VRAM. Larger models take longer to load at startup
  (mind `TimeoutStartSec` in the unit).
