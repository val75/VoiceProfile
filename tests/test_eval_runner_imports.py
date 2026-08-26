"""Regression: the runner must resolve `app`/`services` regardless of cwd.

Running `python scripts/eval_models.py` puts scripts/ on sys.path but not the
repo root, so `from app import create_app` in main() raised ModuleNotFoundError.
This test imports eval_models from a foreign cwd and confirms the app-level
imports it depends on then resolve.
"""

import os
import subprocess
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(REPO_ROOT, "scripts")


def test_app_imports_resolve_from_foreign_cwd(tmp_path):
    code = (
        "import sys;"
        f"sys.path.insert(0, {SCRIPTS!r});"
        "import eval_models;"          # runs the module-level sys.path setup
        "import app, config;"          # the imports main() needs
        "from services.nlp_service import extract_profile_data;"
        "print('IMPORTS_OK')"
    )
    # SECRET_KEY so config.py (loaded transitively by `import app`) doesn't refuse
    # to boot — this test is about import *resolution*, not app configuration.
    env = {**os.environ, "SECRET_KEY": "test-key"}
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(tmp_path),             # NOT the repo root
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "IMPORTS_OK" in result.stdout
