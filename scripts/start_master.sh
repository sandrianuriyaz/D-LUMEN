#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f .env ]]; then set -a; source .env; set +a; fi
: "${DLUMEN_TOKEN:?Set DLUMEN_TOKEN atau buat .env dari .env.example}"
PYTHON_BIN="${DLUMEN_PYTHON:-.venv/bin/python}"
exec "$PYTHON_BIN" -m parallel.master_app
