"""deploy/whisper_probe.sh checks, from the app server, that Whisper transcribes
a short clip sent the way the app sends audio (WHISPER_URL, X-API-Key, "file"
field), and reports to healthchecks.io: a success ping when healthy, a "log"
ping (no status change) with the reason when not, so only a sustained outage
alerts. A real clip, not an empty request, so a full disk or a broken model
counts as down (as on 2026-10-25).

Runs the real script with a fake curl on PATH.
"""
import json
import os
import re
import stat
import subprocess
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "deploy" / "whisper_probe.sh"
STT_SERVICE = ROOT / "services" / "stt_service.py"
HC = "https://hc-ping.com/whisper-uuid"
KEY = "whisper-s3cret"
WHISPER = "http://192.168.100.2:6000/transcribe"

# A request to WHISPER answers FAKE_CODE / FAKE_BODY (or fails with
# FAKE_CURL_EXIT) and keeps a copy of the upload; anything else is a
# healthchecks ping and is only logged.
FAKE_CURL = f"""#!/usr/bin/env python3
import os, shutil, sys
args = sys.argv[1:]
with open(os.environ["CURL_LOG"], "a") as f:
    f.write(" ".join(args) + "\\n")
if args[-1] != "{WHISPER}":
    sys.exit(int(os.environ.get("FAKE_PING_EXIT", "0")))
with open(os.environ["HEADERS_LOG"], "w") as f:
    f.write(sys.stdin.read())
for i, a in enumerate(args):
    if a == "-F":
        field, _, rest = args[i + 1].partition("=@")
        with open(os.environ["FORM_LOG"], "w") as f:
            f.write(field)
        shutil.copy(rest.split(";")[0], os.environ["UPLOAD_COPY"])
if os.environ.get("FAKE_CURL_EXIT"):
    rc = int(os.environ["FAKE_CURL_EXIT"])
    print("curl: (28) Operation timed out" if rc == 28 else "curl: (7) Failed to connect",
          file=sys.stderr)
    sys.exit(rc)
with open(args[args.index("-o") + 1], "w") as f:
    f.write(os.environ.get("FAKE_BODY", ""))
sys.stdout.write(os.environ.get("FAKE_CODE", "200"))
"""

ENV_FILE = (f"WHISPER_URL={WHISPER}\nWHISPER_API_KEY={KEY}\n"
            f"WHISPER_HEALTHCHECK_URL={HC}\n")
OK_BODY = json.dumps({"text": "", "language": "en"})


@pytest.fixture
def probe(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(FAKE_CURL)
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    files = {name: tmp_path / name for name in
             ("curl.log", "headers.log", "form.log", "upload.wav")}

    def _run(env_file=ENV_FILE, **env):
        (tmp_path / ".env").write_text(env_file)
        full_env = {k: v for k, v in os.environ.items() if k != "WHISPER_HEALTHCHECK_URL"}
        full_env.update({
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "APP_DIR": str(tmp_path),
            "TMPDIR": str(scratch),
            "CURL_LOG": str(files["curl.log"]),
            "HEADERS_LOG": str(files["headers.log"]),
            "FORM_LOG": str(files["form.log"]),
            "UPLOAD_COPY": str(files["upload.wav"]),
            "FAKE_BODY": OK_BODY,
            **env,
        })
        proc = subprocess.run(["bash", str(SCRIPT)], env=full_env,
                              capture_output=True, text=True)
        log = files["curl.log"]
        calls = log.read_text().splitlines() if log.exists() else []
        pings = [c for c in calls if "hc-ping.com" in c]
        return proc, pings, calls, files, scratch

    return _run


def test_healthy_sends_a_success_ping(probe):
    proc, pings, _, _, _ = probe()
    assert proc.returncode == 0, proc.stderr
    assert len(pings) == 1
    assert pings[0].split()[-1] == HC


def test_uploads_a_real_wav_in_the_file_field(probe):
    proc, _, _, files, _ = probe()
    assert proc.returncode == 0, proc.stderr
    assert files["form.log"].read_text() == "file"
    with wave.open(str(files["upload.wav"])) as w:
        assert w.getnframes() > 0


def test_upload_is_big_enough_to_be_spooled_to_disk(probe):
    # Starlette keeps uploads up to 1 MiB in memory; a bigger one is written to
    # /tmp while the form is parsed, so a full disk fails the probe there too.
    proc, _, _, files, _ = probe()
    assert proc.returncode == 0, proc.stderr
    assert files["upload.wav"].stat().st_size > 1024 * 1024


def test_waits_as_long_as_the_app_does(probe):
    # Whisper transcribes one request at a time, so the probe can queue behind a
    # worker's recording; giving up sooner than the app would be a false alarm.
    app_timeout = re.search(r"timeout=(\d+)", STT_SERVICE.read_text()).group(1)
    proc, _, calls, _, _ = probe()
    whisper_call = next(c for c in calls if c.endswith(WHISPER))
    assert f"-m {app_timeout} " in whisper_call


def test_whisper_error_logs_its_status_and_reason(probe):
    body = json.dumps({"detail": "transcription failed: OSError: [Errno 28] No space left on device"})
    proc, pings, _, _, _ = probe(FAKE_CODE="500", FAKE_BODY=body)
    assert proc.returncode != 0
    assert len(pings) == 1
    assert pings[0].split()[-1] == f"{HC}/log"
    assert "HTTP 500" in pings[0]
    assert "No space left on device" in pings[0]


def test_rejected_key_is_a_failure(probe):
    proc, pings, _, _, _ = probe(FAKE_CODE="401",
                                 FAKE_BODY='{"detail":"Invalid or missing API key"}')
    assert proc.returncode != 0
    assert pings[0].split()[-1] == f"{HC}/log"
    assert "HTTP 401" in pings[0]


def test_unreachable_logs_the_curl_error(probe):
    proc, pings, _, _, _ = probe(FAKE_CURL_EXIT="7")
    assert proc.returncode != 0
    assert pings[0].split()[-1] == f"{HC}/log"
    assert "cannot reach" in pings[0]
    assert "Failed to connect" in pings[0]


def test_timeout_is_reported_as_no_response_not_unreachable(probe):
    # Connected but no answer points at a hung model or GPU, not the network.
    proc, pings, _, _, _ = probe(FAKE_CURL_EXIT="28")
    assert proc.returncode != 0
    assert "no response" in pings[0]
    assert "cannot reach" not in pings[0]


@pytest.mark.parametrize("body", ["<html>oops</html>", '{"language": "en"}', '{"text": null}'])
def test_200_without_a_transcript_is_a_failure(probe, body):
    proc, pings, _, _, _ = probe(FAKE_BODY=body)
    assert proc.returncode != 0
    assert pings[0].split()[-1] == f"{HC}/log"


def test_key_goes_in_a_header_not_on_the_command_line(probe):
    # Command lines are visible to every user in `ps`.
    proc, _, calls, files, _ = probe()
    assert proc.returncode == 0, proc.stderr
    assert f"X-API-Key: {KEY}" in files["headers.log"].read_text()
    assert not any(KEY in c for c in calls)


@pytest.mark.parametrize("missing", ["WHISPER_URL", "WHISPER_API_KEY"])
def test_missing_setting_is_a_failure(probe, missing):
    env = "\n".join(l for l in ENV_FILE.splitlines() if not l.startswith(f"{missing}=")) + "\n"
    proc, pings, calls, _, _ = probe(env)
    assert proc.returncode != 0
    assert len(calls) == 1  # just the log ping
    assert pings[0].split()[-1] == f"{HC}/log"
    assert missing in pings[0]


def test_temp_files_are_removed(probe):
    for kwargs in ({}, {"FAKE_CODE": "500"}):
        _, _, _, _, scratch = probe(**kwargs)
        assert list(scratch.iterdir()) == []


def test_unit_environment_overrides_env_file(probe):
    other = "https://hc-ping.com/other-uuid"
    _, pings, _, _, _ = probe(WHISPER_HEALTHCHECK_URL=other)
    assert pings[0].split()[-1] == other


def test_no_url_means_no_ping_but_still_reports_health(probe):
    env = "\n".join(l for l in ENV_FILE.splitlines() if "HEALTHCHECK" not in l) + "\n"
    proc, pings, _, _, _ = probe(env)
    assert proc.returncode == 0, proc.stderr
    assert pings == []
    proc, pings, _, _, _ = probe(env, FAKE_CODE="500")
    assert proc.returncode != 0
    assert pings == []


def test_failed_ping_does_not_fail_a_healthy_probe(probe):
    proc, _, _, _, _ = probe(FAKE_PING_EXIT="6")
    assert proc.returncode == 0, proc.stderr
    assert "ping failed" in proc.stdout + proc.stderr
