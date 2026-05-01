#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="$SCRIPT_DIR/ytm-auth.conf"

if [[ ! -f "$CONF" ]]; then
  echo "Config not found. Copy scripts/ytm-auth.conf.example to scripts/ytm-auth.conf and fill in your credentials."
  exit 1
fi

source "$CONF"

echo "=== List accounts ==="
curl -s "$HOST/streaming/accounts" | jq .
echo ""

echo "=== List playlists ==="
curl -s "$HOST/streaming/playlists" | jq .
echo ""

echo "=== Enqueue sync for account 1 ==="
curl -s -X POST "$HOST/streaming/accounts/1/sync" \
  -H 'Content-Type: application/json' \
  -d "{\"client_id\":\"$CLIENT_ID\",\"client_secret\":\"$CLIENT_SECRET\"}" | jq .
