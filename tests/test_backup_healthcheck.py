"""deploy/backup_db.sh reports every run to healthchecks.io when HEALTHCHECK_URL
is set, so a failed backup, or one that never runs at all, sends an alert.

Runs the real script with fake pg_dump and curl on PATH and no off-box copy.
"""
import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "backup_db.sh"
URL = "https://hc-ping.com/test-uuid"

FAKE_PG_DUMP = """#!/bin/sh
if [ -n "$FAKE_PG_DUMP_FAIL" ]; then echo "pg_dump: error: connection failed" >&2; exit 1; fi
for a in "$@"; do case "$a" in --file=*) echo dump > "${a#--file=}";; esac; done
"""
FAKE_CURL = """#!/bin/sh
echo "$@" >> "$CURL_LOG"
exit "${FAKE_CURL_EXIT:-0}"
"""


@pytest.fixture
def run_backup(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("pg_dump", FAKE_PG_DUMP), ("curl", FAKE_CURL)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    curl_log = tmp_path / "curl.log"

    def _run(env_file="DATABASE_URL=postgresql://u:p@localhost/db\n", **env):
        (tmp_path / ".env").write_text(env_file)
        full_env = {k: v for k, v in os.environ.items() if k != "HEALTHCHECK_URL"}
        full_env.update({
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "APP_DIR": str(tmp_path),
            "BACKUP_DIR": str(tmp_path / "backups"),
            "DGX_HOST": "",
            "CURL_LOG": str(curl_log),
            **env,
        })
        proc = subprocess.run(["bash", str(SCRIPT)], env=full_env,
                              capture_output=True, text=True)
        pings = curl_log.read_text().splitlines() if curl_log.exists() else []
        return proc, pings

    return _run


def with_url(url=URL):
    return f"DATABASE_URL=postgresql://u:p@localhost/db\nHEALTHCHECK_URL={url}\n"


def test_success_pings_exit_status_0(run_backup):
    proc, pings = run_backup(with_url())
    assert proc.returncode == 0, proc.stderr
    assert len(pings) == 1
    assert pings[0].endswith(f"{URL}/0")


def test_failed_dump_pings_its_exit_status(run_backup):
    proc, pings = run_backup(with_url(), FAKE_PG_DUMP_FAIL="1")
    assert proc.returncode == 1
    assert len(pings) == 1
    assert pings[0].endswith(f"{URL}/1")


def test_missing_database_url_still_pings_failure(run_backup):
    proc, pings = run_backup(f"HEALTHCHECK_URL={URL}\n")
    assert proc.returncode != 0
    assert len(pings) == 1
    assert not pings[0].endswith(f"{URL}/0")


def test_quoted_url_with_trailing_slash(run_backup):
    proc, pings = run_backup(with_url(f'"{URL}/"'))
    assert proc.returncode == 0, proc.stderr
    assert pings[0].endswith(f"{URL}/0")


def test_unit_environment_overrides_env_file(run_backup):
    other = "https://hc-ping.com/other-uuid"
    proc, pings = run_backup(with_url(), HEALTHCHECK_URL=other)
    assert pings[0].endswith(f"{other}/0")


def test_no_url_means_no_ping(run_backup):
    proc, pings = run_backup()
    assert proc.returncode == 0, proc.stderr
    assert pings == []


def test_failed_ping_does_not_fail_the_backup(run_backup):
    # healthchecks.io alerts on the missing ping anyway; the backup itself is fine.
    proc, pings = run_backup(with_url(), FAKE_CURL_EXIT="7")
    assert proc.returncode == 0, proc.stderr
    assert "healthcheck ping failed" in proc.stdout + proc.stderr
