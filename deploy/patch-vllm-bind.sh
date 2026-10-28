#!/usr/bin/env bash
#
# Make vLLM 0.6.3.post1 honour --host.
#
# vllm 0.6.3.post1 opens its port itself with sock.bind(("", args.port)), i.e. on
# every interface, and hands that socket to uvicorn, so --host has no effect.
# The DGX has a public IP, so vLLM would listen there too (ufw and the API key
# still stand in front of it). This applies vLLM 0.6.4's one-line fix:
#
#     sock.bind((args.host or "", args.port))
#
# build-vllm-venv.sh runs it. deploy/vllm-qwen.service runs it with --check
# before every start and refuses to start vLLM without the fix, so a reinstall
# can't silently undo it.
#
# Safe to re-run: does nothing if the fix is already there (or on vllm >= 0.6.4).
#
# Usage:   bash deploy/patch-vllm-bind.sh [--check]
#          --check: change nothing; exit 1 unless the fix is in place.
# Optional: VENV=/path/to/vllm-venv bash deploy/patch-vllm-bind.sh
#
set -euo pipefail

CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1
VENV="${VENV:-$HOME/vllm-venv}"

UNPATCHED='sock\.bind(("", args\.port))'
FIXED='args\.host or ""'

shopt -s nullglob
servers=("$VENV"/lib/python3*/site-packages/vllm/entrypoints/openai/api_server.py)
if [ "${#servers[@]}" -eq 0 ]; then
    echo "ERROR: no vllm/entrypoints/openai/api_server.py under $VENV" >&2
    exit 1
fi

status=0
for server in "${servers[@]}"; do
    # Fixed = the 0.6.3 bind line is gone and the fix (or 0.6.4's form) is there.
    if ! grep -q "$UNPATCHED" "$server" && grep -q "$FIXED" "$server"; then
        echo "OK: $server binds --host"
    elif [ "$CHECK" = 1 ]; then
        echo "vLLM would ignore --host and listen on every interface:" \
             "$server is not patched; run deploy/patch-vllm-bind.sh" >&2
        status=1
    elif grep -q "$UNPATCHED" "$server"; then
        sed -i.orig "s/$UNPATCHED/sock.bind((args.host or \"\", args.port))/" "$server"
        echo "Patched $server (original kept as $server.orig); restart vllm-qwen to apply."
    else
        echo "ERROR: $server has neither the 0.6.3 bind line nor the fix;" \
             "check how this vLLM version binds before patching by hand" >&2
        status=1
    fi
done
exit "$status"
