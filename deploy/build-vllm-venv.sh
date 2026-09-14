#!/usr/bin/env bash
#
# Reproducibly build the vLLM serving venv on the DGX-2 (Volta / V100, sm_70).
#
# Why every pin here is deliberate (all learned the hard way — see
# tasks/vllm-eval-plan.md):
#   - The current vLLM/torch line DROPPED Volta (sm_70). vllm 0.6.3.post1 is the
#     newest that still pulls a Volta-capable torch (2.4.0+cu121, which ships
#     sm_70 kernels) AND supports Qwen2.5 + tensor-parallel.
#   - transformers must be pinned DOWN to 4.45.2: vllm 0.6.3's range otherwise
#     resolves a newer transformers that requires torch >= 2.5 and silently
#     disables its PyTorch backend ("Models won't be available").
#   - vLLM imports outlines -> pyairports on EVERY request (even with guided
#     decoding unused, i.e. LLM_JSON_MODE=off). PyPI's pyairports is a broken
#     0.0.1 stub; fix-pyairports.sh installs the real one from GitHub and pins
#     setuptools<81 (pyairports needs the removed pkg_resources API).
#
# Requires: python3, and git (for the GitHub pyairports install). Internet to
# the pip index, github.com, and public PyPI.
#
# Usage:   bash deploy/build-vllm-venv.sh
# Optional: VENV=/path/to/vllm-venv bash deploy/build-vllm-venv.sh
# Produces the venv that deploy/vllm-qwen.service runs.
#
set -euo pipefail

VENV="${VENV:-$HOME/vllm-venv}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -e "$VENV" ]; then
    echo "ERROR: $VENV already exists. For a clean rebuild remove it first:" >&2
    echo "  rm -rf $VENV" >&2
    exit 1
fi

python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip wheel

# Volta-compatible pinned stack. vllm pulls torch 2.4.0+cu121 (has sm_70),
# outlines, and xformers automatically; the verify step below asserts sm_70 is
# actually present. If the box's default pip index (internal mirror) lacks a
# package, add:  --extra-index-url https://pypi.org/simple/
"$VENV/bin/pip" install "vllm==0.6.3.post1"
"$VENV/bin/pip" install "transformers==4.45.2"

# Repair pyairports (PyPI 0.0.1 stub -> real GitHub package) + setuptools<81.
VENV="$VENV" bash "$SCRIPT_DIR/fix-pyairports.sh"

# --- Verify the Volta gate + the deps that bit us, fail loudly if regressed ---
"$VENV/bin/python" - <<'PY'
import torch, transformers, vllm
from transformers.utils import is_torch_available

assert "sm_70" in torch.cuda.get_arch_list(), \
    f"torch has no sm_70 (Volta) kernels: {torch.cuda.get_arch_list()}"
assert is_torch_available(), \
    "transformers disabled its PyTorch backend (transformers too new for this torch)"

print("OK: vllm", vllm.__version__,
      "| torch", torch.__version__,
      "| transformers", transformers.__version__,
      "| sm_70 present")
PY

echo
echo "Built $VENV successfully. Run it via deploy/vllm-qwen.service on the DGX-2."
