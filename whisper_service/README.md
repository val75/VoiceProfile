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
# 1. Get the code into ~/VoiceProfile (the whole repo; only whisper_service/ is used here)
cd ~ && git clone https://github.com/val75/VoiceProfile.git
cd VoiceProfile/whisper_service

# 2. venv + deps, OUTSIDE the checkout at ~/whisper_service/venv (the unit's path)
python3 -m venv ~/whisper_service/venv
~/whisper_service/venv/bin/pip install -r requirements.txt
#    NOTE: torch must match the DGX's CUDA. If pip pulls a CPU-only or wrong-CUDA
#    build, install torch from the correct index first (see pytorch.org), then
#    the rest of requirements.txt.

# 3. Sanity-check the model loads and transcribes (first run downloads the model)
~/whisper_service/venv/bin/python - <<'PY'
import torch, whisper
print("CUDA available:", torch.cuda.is_available())
m = whisper.load_model("medium")
print(m.transcribe("some_speech.wav")["text"])
PY

# 4. Run under systemd
sudo install -m 600 -o root -g root /dev/null /etc/whisper.env
sudoedit /etc/whisper.env    # WHISPER_API_KEY=<same value as the app's .env>
sudo cp whisper.service /etc/systemd/system/whisper.service
sudo systemctl daemon-reload
sudo systemctl enable --now whisper
sudo journalctl -u whisper -f                      # wait for "Application startup complete"
```

## Updating

```bash
cd ~/VoiceProfile && git pull
sudo systemctl restart whisper
# if whisper.service changed, reinstall it first:
#   sudo cp whisper_service/whisper.service /etc/systemd/system/ && sudo systemctl daemon-reload
```

uvicorn does not hot-reload in production, so **always restart after a code
change** — a stale process silently running old code caused a hard-to-find
outage once (the handler returned `null` for every request).

## Notes

- **Binding.** The unit runs `--host 192.168.100.2`, the DGX's private-network
  address, because the DGX also has a public IP. ufw additionally allows port
  6000 only from `192.168.100.0/24`. To test by hand on the DGX, call
  `192.168.100.2:6000`, not `localhost:6000`. (If Ollama is ever re-enabled on
  the DGX, set `OLLAMA_HOST=127.0.0.1:11434`: an open Ollama filled the disk
  on 2026-10-25 and took this service down.)
- **API key.** Every request must send `X-API-Key` equal to `WHISPER_API_KEY`,
  else 401 (checked before the upload is read). The unit loads it from
  `/etc/whisper.env` (root-owned, 0600); use the same value as the app's
  `WHISPER_API_KEY`. The service refuses to start if it's unset.
- **Errors.** A failed transcription returns a JSON 500 with the reason
  (e.g. `OSError: [Errno 28] No space left on device`); the app logs it.
- **Tests.** `~/whisper_service/venv/bin/pip install pytest httpx2`, then
  `~/whisper_service/venv/bin/python -m pytest test_app.py` (Whisper is stubbed; no model load).
- **Model size.** `whisper.load_model("medium")` — swap for `small`/`large`
  to trade accuracy for speed/VRAM. Larger models take longer to load at startup
  (mind `TimeoutStartSec` in the unit).
