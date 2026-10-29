"""vLLM 0.6.3.post1 ignores --host: it binds ("", port), every interface.

deploy/patch-vllm-bind.sh applies the 0.6.4 fix to a venv; with --check it
changes nothing and fails unless the fix is in place. deploy/vllm-qwen.service
runs the --check before every start, so a reinstall can't silently undo the fix.
All of it runs here against excerpts of the real api_server.py.
"""
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PATCH_SCRIPT = ROOT / "deploy" / "patch-vllm-bind.sh"
UNIT = ROOT / "deploy" / "vllm-qwen.service"

# vllm/entrypoints/openai/api_server.py, run_server(), as shipped in each version.
V063 = '''    # see https://github.com/vllm-project/vllm/issues/8204
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("", args.port))

    def signal_handler(*_) -> None:
'''
V063_PATCHED = V063.replace('sock.bind(("", args.port))',
                            'sock.bind((args.host or "", args.port))')
V064 = '''    # see https://github.com/vllm-project/vllm/issues/8204
    sock_addr = (args.host or "", args.port)
    sock = create_server_socket(sock_addr)
'''
UNKNOWN = '''    sock = make_socket(args)
'''


def server_path(venv_dir, python="python3.10"):
    return (venv_dir / "lib" / python / "site-packages" / "vllm"
            / "entrypoints" / "openai" / "api_server.py")


@pytest.fixture
def venv(tmp_path):
    """A fake venv holding api_server.py with the given contents."""
    def _make(source, python="python3.10"):
        server = server_path(tmp_path / "venv", python)
        server.parent.mkdir(parents=True)
        server.write_text(source)
        return tmp_path / "venv", server
    return _make


def run_patch(venv_dir, *args):
    return subprocess.run(["bash", str(PATCH_SCRIPT), *args],
                          env={"VENV": str(venv_dir), "PATH": "/usr/bin:/bin"},
                          capture_output=True, text=True)


def guard_line():
    lines = [l for l in UNIT.read_text().splitlines()
             if l.startswith("ExecStartPre=") and "patch-vllm-bind.sh" in l]
    assert len(lines) == 1, lines
    return lines[0]


def run_guard(venv_dir):
    """Run the unit's guard ExecStartPre against this repo's script and venv_dir."""
    argv = shlex.split(guard_line().split("=", 1)[1])
    argv = [str(PATCH_SCRIPT) if a.endswith("/deploy/patch-vllm-bind.sh")
            else f"VENV={venv_dir}" if a.startswith("VENV=") else a
            for a in argv]
    return subprocess.run(argv, capture_output=True, text=True)


# --- patching ----------------------------------------------------------------

def test_patch_fixes_the_063_bind(venv):
    venv_dir, server = venv(V063)
    proc = run_patch(venv_dir)
    assert proc.returncode == 0, proc.stderr
    assert server.read_text() == V063_PATCHED


def test_patch_is_a_noop_when_already_patched(venv):
    venv_dir, server = venv(V063_PATCHED)
    proc = run_patch(venv_dir)
    assert proc.returncode == 0, proc.stderr
    assert server.read_text() == V063_PATCHED


def test_patch_is_a_noop_on_064(venv):
    venv_dir, server = venv(V064)
    assert run_patch(venv_dir).returncode == 0
    assert server.read_text() == V064


def test_patch_refuses_unknown_code(venv):
    venv_dir, server = venv(UNKNOWN)
    proc = run_patch(venv_dir)
    assert proc.returncode != 0
    assert server.read_text() == UNKNOWN
    assert "api_server.py" in proc.stderr


def test_patch_fails_without_vllm(tmp_path):
    proc = run_patch(tmp_path / "no-venv")
    assert proc.returncode != 0
    assert "api_server.py" in proc.stderr


def test_patch_still_fixes_the_bind_when_the_fix_text_appears_elsewhere(venv):
    # The fix's text in a comment must not count: the bind line itself decides.
    source = '    # upstream: (args.host or "", args.port)\n' + V063
    venv_dir, server = venv(source)
    assert run_patch(venv_dir).returncode == 0
    assert 'sock.bind(("", args.port))' not in server.read_text()


def test_patch_fixes_every_python_dir(venv):
    venv_dir, first = venv(V063, "python3.10")
    second = server_path(venv_dir, "python3.12")
    second.parent.mkdir(parents=True)
    second.write_text(V063)
    assert run_patch(venv_dir).returncode == 0
    assert first.read_text() == V063_PATCHED
    assert second.read_text() == V063_PATCHED


# --- --check -----------------------------------------------------------------

@pytest.mark.parametrize("source", [V063, UNKNOWN], ids=["0.6.3", "unknown"])
def test_check_fails_and_changes_nothing_unless_fixed(venv, source):
    venv_dir, server = venv(source)
    proc = run_patch(venv_dir, "--check")
    assert proc.returncode != 0
    assert "patch-vllm-bind.sh" in proc.stderr
    assert server.read_text() == source


@pytest.mark.parametrize("source", [V063_PATCHED, V064], ids=["0.6.3-patched", "0.6.4"])
def test_check_passes_when_fixed(venv, source):
    venv_dir, _ = venv(source)
    proc = run_patch(venv_dir, "--check")
    assert proc.returncode == 0, proc.stderr


def test_check_fails_when_the_fix_text_appears_but_the_bind_is_unpatched(venv):
    venv_dir, _ = venv('    # upstream: (args.host or "", args.port)\n' + V063)
    assert run_patch(venv_dir, "--check").returncode != 0


def test_check_fails_if_any_python_dir_is_unpatched(venv):
    venv_dir, _ = venv(V063_PATCHED, "python3.10")
    second = server_path(venv_dir, "python3.12")
    second.parent.mkdir(parents=True)
    second.write_text(V063)
    assert run_patch(venv_dir, "--check").returncode != 0


def test_check_fails_without_vllm(tmp_path):
    assert run_patch(tmp_path / "no-venv", "--check").returncode != 0


# --- the unit's guard ----------------------------------------------------------

def test_guard_blocks_unpatched_063(venv):
    venv_dir, server = venv(V063)
    proc = run_guard(venv_dir)
    assert proc.returncode != 0
    assert "patch-vllm-bind.sh" in proc.stderr
    assert server.read_text() == V063


def test_guard_allows_patched_063(venv):
    venv_dir, _ = venv(V063_PATCHED)
    proc = run_guard(venv_dir)
    assert proc.returncode == 0, proc.stderr


def test_guard_points_at_the_units_venv():
    line = guard_line()
    assert "VENV=/home/cato-user/vllm-venv" in line
    assert "/home/cato-user/vllm-venv/bin/vllm" in UNIT.read_text()
    assert "--check" in line


def test_guard_line_is_safe_for_systemd():
    # systemd expands $VAR and %-specifiers in Exec lines; the guard uses neither.
    line = guard_line()
    assert "$" not in line and "%" not in line
