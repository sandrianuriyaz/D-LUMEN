#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
ROLE="${1:-worker}"
if [[ "$ROLE" != "master" && "$ROLE" != "worker" ]]; then echo "usage: $0 [master|worker]"; exit 2; fi
PYTHON_CMD="${DLUMEN_BOOTSTRAP_PYTHON:-python3}"
if [[ ! -d .venv ]]; then "$PYTHON_CMD" -m venv .venv; fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r "requirements-${ROLE}.txt"
echo "SETUP OK: $(hostname) role=$ROLE"
