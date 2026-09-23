#!/usr/bin/env bash
#
# Fix pyairports for older Outlines/vLLM installations.
#
# Problem:
#   outlines==0.0.46 requires "pyairports", but pip may install
#   pyairports==0.0.1 from PyPI, which contains only metadata/sample files
#   and does NOT provide:
#
#       from pyairports.airports import AIRPORT_LIST
#
# The correct pyairports implementation is installed from its Git repository.
#
# pyairports uses pkg_resources, so setuptools must remain <81.
#
# Usage:
#   ./fix_pyairports.sh
#
# Optional:
#   VENV=/path/to/vllm-venv ./fix_pyairports.sh
#

set -euo pipefail

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

VENV="${VENV:-$HOME/vllm-venv}"
PYTHON="$VENV/bin/python"

echo "============================================================"
echo "pyairports / Outlines repair"
echo "============================================================"
echo

# -------------------------------------------------------------------
# Verify virtual environment
# -------------------------------------------------------------------

if [[ ! -x "$PYTHON" ]]; then
        echo "ERROR: Python not found:"
        echo "  $PYTHON"
        echo
        echo "Set VENV to your virtual environment, for example:"
        echo "  VENV=/path/to/vllm-venv $0"
        exit 1
fi

echo "Using Python:"
"$PYTHON" -c 'import sys; print(sys.executable)'
echo

echo "Python version:"
"$PYTHON" --version
echo

# -------------------------------------------------------------------
# Show current state
# -------------------------------------------------------------------

echo "Current pyairports installation:"
"$PYTHON" -m pip show pyairports 2>/dev/null || echo "pyairports is not currently installed"
echo

echo "Testing current pyairports import..."
if "$PYTHON" -c "from pyairports.airports import AIRPORT_LIST; print(f'Current AIRPORT_LIST size: {len(AIRPORT_LIST)}')" 2>/dev/null; then
        echo
        echo "pyairports already works."
        echo "No repair is necessary."

        echo
        echo "Checking setuptools compatibility..."
        "$PYTHON" -c "import pkg_resources; print('pkg_resources available')" 2>/dev/null || {
                echo "pkg_resources is missing; repairing setuptools..."
                "$PYTHON" -m pip install --upgrade "setuptools<81"
        }

        echo
        echo "Final verification:"
        "$PYTHON" -c "
from pyairports.airports import AIRPORT_LIST
print(f'pyairports OK: {len(AIRPORT_LIST)} airports')
"
        exit 0
fi

echo "Current pyairports import is broken."
echo "Beginning repair..."
echo

# -------------------------------------------------------------------
# Remove the broken/wrong PyPI package
# -------------------------------------------------------------------

echo "[1/5] Removing existing pyairports installation..."

"$PYTHON" -m pip uninstall -y pyairports || true

echo

# Remove any leftover package metadata or directories.
# This handles cases where pip reports the package as installed but
# only a broken *.dist-info directory remains.

SITE_PACKAGES="$(
    "$PYTHON" -c '
import site
paths = site.getsitepackages()
print(paths[0] if paths else "")
'
)"

if [[ -z "$SITE_PACKAGES" || ! -d "$SITE_PACKAGES" ]]; then
        echo "ERROR: Could not determine site-packages directory."
        exit 1
fi

echo "Cleaning leftover pyairports files from:"
echo "  $SITE_PACKAGES"

rm -rf \
        "$SITE_PACKAGES/pyairports" \
        "$SITE_PACKAGES/pyairports-"*.dist-info \
        "$SITE_PACKAGES/pyairports-"*.egg-info

echo

# -------------------------------------------------------------------
# Install setuptools compatible with pkg_resources
# -------------------------------------------------------------------

echo "[2/5] Installing compatible setuptools..."
echo "       pyairports uses the deprecated pkg_resources API."
echo

"$PYTHON" -m pip install --upgrade "setuptools<81"

echo

# Verify pkg_resources is available.

echo "[3/5] Verifying pkg_resources..."

if ! "$PYTHON" -c "import pkg_resources; print('pkg_resources OK')" 2>/dev/null; then
        echo "ERROR: pkg_resources is still unavailable after installing setuptools."
        exit 1
fi

echo

# -------------------------------------------------------------------
# Install the correct pyairports implementation
# -------------------------------------------------------------------

echo "[4/5] Installing correct pyairports from GitHub..."
echo

"$PYTHON" -m pip install --no-cache-dir \
        "pyairports @ git+https://github.com/ozeliger/pyairports.git"

echo

# -------------------------------------------------------------------
# Verify
# -------------------------------------------------------------------

echo "[5/5] Verifying pyairports..."

"$PYTHON" -c "
from pyairports.airports import AIRPORT_LIST

count = len(AIRPORT_LIST)

if count == 0:
    raise RuntimeError('AIRPORT_LIST is empty')

print(f'pyairports successfully installed')
print(f'AIRPORT_LIST contains: {count} airports')
"

echo

echo "Checking Python package dependencies..."
"$PYTHON" -m pip check

echo

echo "Checking Outlines import..."

"$PYTHON" -c "
import outlines
from outlines.types.airports import AIRPORT_LIST

print('Outlines OK')
print(f'Outlines can access AIRPORT_LIST: {len(AIRPORT_LIST)} airports')
"

echo
echo "============================================================"
echo "SUCCESS"
echo "============================================================"
echo
echo "The pyairports / Outlines dependency problem has been repaired."
echo
echo "Important:"
echo "  pyairports uses pkg_resources, so keep setuptools below version 81."
echo
echo "Recommended pins:"
echo "  pyairports    -> installed from ozeliger/pyairports"
echo "  setuptools    -> <81"
echo
