#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_CMD="${DLUMEN_BOOTSTRAP_PYTHON:-python3}"
if [[ ! -d .venv ]]; then "$PYTHON_CMD" -m venv .venv; fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
echo "SETUP OK: $(hostname)"
