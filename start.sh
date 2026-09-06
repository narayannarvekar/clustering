#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
VENV_DIR="$BACKEND_DIR/.venv"
PORT="${PORT:-8000}"

if ! command -v uv &> /dev/null; then
  echo "uv is not installed. Install it with:"
  echo "  curl -LsSf https://astral.sh/install.sh | sh"
  echo "or: brew install uv"
  exit 1
fi

cd "$BACKEND_DIR"

if [ ! -d "$VENV_DIR" ]; then
  echo "No virtual environment found — creating one and installing dependencies..."
  uv venv .venv --python 3.12
  uv pip install --python .venv/bin/python -r requirements.txt
fi

echo "Starting server at http://localhost:${PORT}"
exec .venv/bin/uvicorn app.main:app --reload --port "$PORT"
