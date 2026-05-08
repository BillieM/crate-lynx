#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENAPI_PATH="$ROOT_DIR/openapi.json"

cd "$ROOT_DIR"

source .venv/bin/activate
PYTHONPATH="$ROOT_DIR/app" python -m app.openapi_export > "$OPENAPI_PATH"
npx --prefix "$ROOT_DIR/app-ui" openapi-typescript "$OPENAPI_PATH" -o "$ROOT_DIR/app-ui/src/lib/api-types.ts"
