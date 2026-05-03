#!/bin/bash
# Test YouTube Music endpoints against the running app.
# Usage: HOST=http://localhost:8000 ./ytm-test.sh [account_id]
set -euo pipefail

HOST="${HOST:-http://192.168.0.203:18101}"
ACCOUNT_ID="${1:-}"

echo "=== Accounts ==="
ACCOUNTS=$(curl -s "$HOST/streaming/accounts")
echo "$ACCOUNTS" | jq .
echo ""

if [[ -z "$ACCOUNT_ID" ]]; then
  echo "$ACCOUNTS" | jq -r '.accounts[] | "\(.id): \(.display_name) [\(.auth_state)]"'
  read -rp "Account ID to sync: " ACCOUNT_ID
fi

SYNC_WAIT="${SYNC_WAIT:-5}"

if [[ -n "$ACCOUNT_ID" ]]; then
  echo "=== Enqueue sync for account $ACCOUNT_ID ==="
  curl -s -X POST "$HOST/streaming/accounts/$ACCOUNT_ID/sync" \
    -H "Content-Type: application/json" | jq .
  echo ""
  echo "Waiting ${SYNC_WAIT}s for sync..."
  sleep "$SYNC_WAIT"
else
  echo "(No accounts found — skipping sync)"
fi

echo "=== Playlists ==="
curl -s "$HOST/streaming/playlists" | jq .
echo ""
