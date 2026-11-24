#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f .env ]]; then set -a; source .env; set +a; fi
PYTHON_BIN="${DLUMEN_PYTHON:-.venv/bin/python}"
exec "$PYTHON_BIN" -m master.master_server
