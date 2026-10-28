"""deploy/vllm_probe.sh checks, from the app server, that the LLM the app uses
answers with the app's key and serves the app's model, and reports to
healthchecks.io: a success ping when healthy, a "log" ping (no status change)
with the reason when not, so only a sustained outage alerts.

Runs the real script with a fake curl on PATH.
"""
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "vllm_probe.sh"
HC = "https://hc-ping.com/vllm-uuid"
KEY = "s3cret-key"
MODELS = json.dumps({"object": "list", "data": [{"id": "qwen2.5-32b", "object": "model"}]})

# Requests to the LLM (URL ending in /models) print FAKE_MODELS or fail with
# FAKE_LLM_EXIT; anything else is a healthchecks ping and is only logged.
FAKE_CURL = """#!/bin/sh
echo "$@" >> "$CURL_LOG"
for a in "$@"; do last="$a"; done
case "$last" in
  */models)
    cat > "$HEADERS_LOG"
    echo "$last" > "$MODELS_URL_LOG"
    if [ -n "$FAKE_LLM_EXIT" ]; then
      echo "curl: ($FAKE_LLM_EXIT) simulated failure" >&2; exit "$FAKE_LLM_EXIT"
    fi
    printf '%s' "$FAKE_MODELS" ;;
  *) exit "${FAKE_PING_EXIT:-0}" ;;
esac
"""

ENV_FILE = (f"LLM_URL=http://192.168.100.2:8000/v1\nLLM_MODEL=qwen2.5-32b\n"
            f"LLM_API_KEY={KEY}\nVLLM_HEALTHCHECK_URL={HC}\n")


@pytest.fixture
def probe(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(FAKE_CURL)
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    logs = {name: tmp_path / f"{name}.log" for name in ("curl", "headers", "models_url")}

    def _run(env_file=ENV_FILE, **env):
        (tmp_path / ".env").write_text(env_file)
        full_env = {k: v for k, v in os.environ.items() if k != "VLLM_HEALTHCHECK_URL"}
        full_env.update({
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "APP_DIR": str(tmp_path),
            "CURL_LOG": str(logs["curl"]),
            "HEADERS_LOG": str(logs["headers"]),
            "MODELS_URL_LOG": str(logs["models_url"]),
            "FAKE_MODELS": MODELS,
            **env,
        })
        proc = subprocess.run(["bash", str(SCRIPT)], env=full_env,
                              capture_output=True, text=True)
        calls = logs["curl"].read_text().splitlines() if logs["curl"].exists() else []
        pings = [c for c in calls if "hc-ping.com" in c]
        return proc, pings, calls, logs

    return _run


def test_healthy_sends_a_success_ping(probe):
    proc, pings, _, logs = probe()
    assert proc.returncode == 0, proc.stderr
    assert len(pings) == 1
    assert pings[0].split()[-1] == HC
    assert logs["models_url"].read_text().strip() == "http://192.168.100.2:8000/v1/models"


def test_unreachable_logs_the_reason_without_a_success_ping(probe):
    proc, pings, _, _ = probe(FAKE_LLM_EXIT="7")
    assert proc.returncode != 0
    assert len(pings) == 1
    assert pings[0].split()[-1] == f"{HC}/log"
    assert "simulated failure" in pings[0]


def test_rejected_key_is_a_failure(probe):
    proc, pings, _, _ = probe(FAKE_LLM_EXIT="22")
    assert proc.returncode != 0
    assert pings[0].split()[-1] == f"{HC}/log"


def test_model_not_served_is_a_failure(probe):
    other = json.dumps({"object": "list", "data": [{"id": "mistral:7b-instruct"}]})
    proc, pings, _, _ = probe(FAKE_MODELS=other)
    assert proc.returncode != 0
    assert pings[0].split()[-1] == f"{HC}/log"
    assert "qwen2.5-32b" in pings[0]


def test_garbage_response_is_a_failure(probe):
    proc, pings, _, _ = probe(FAKE_MODELS="<html>oops</html>")
    assert proc.returncode != 0
    assert pings[0].split()[-1] == f"{HC}/log"


def test_key_goes_in_a_header_not_on_the_command_line(probe):
    # Command lines are visible to every user in `ps`.
    proc, _, calls, logs = probe()
    assert proc.returncode == 0, proc.stderr
    assert f"Authorization: Bearer {KEY}" in logs["headers"].read_text()
    assert not any(KEY in c for c in calls)


def test_trailing_slash_on_llm_url(probe):
    env = ENV_FILE.replace("/v1\n", '/v1/"\n').replace("LLM_URL=", 'LLM_URL="')
    proc, _, _, logs = probe(env)
    assert proc.returncode == 0, proc.stderr
    assert logs["models_url"].read_text().strip() == "http://192.168.100.2:8000/v1/models"


def test_unit_environment_overrides_env_file(probe):
    other = "https://hc-ping.com/other-uuid"
    proc, pings, _, _ = probe(VLLM_HEALTHCHECK_URL=other)
    assert pings[0].split()[-1] == other


def test_no_url_means_no_ping_but_still_reports_health(probe):
    env = "\n".join(l for l in ENV_FILE.splitlines() if "HEALTHCHECK" not in l) + "\n"
    proc, pings, _, _ = probe(env)
    assert proc.returncode == 0, proc.stderr
    assert pings == []
    proc, pings, _, _ = probe(env, FAKE_LLM_EXIT="7")
    assert proc.returncode != 0
    assert pings == []


def test_failed_ping_does_not_fail_a_healthy_probe(probe):
    proc, _, _, _ = probe(FAKE_PING_EXIT="6")
    assert proc.returncode == 0, proc.stderr
    assert "ping failed" in proc.stdout + proc.stderr
