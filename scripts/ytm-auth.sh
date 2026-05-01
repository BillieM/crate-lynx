#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="$SCRIPT_DIR/ytm-auth.conf"

if [[ ! -f "$CONF" ]]; then
  echo "Config not found. Copy scripts/ytm-auth.conf.example to scripts/ytm-auth.conf and fill in your credentials."
  exit 1
fi

source "$CONF"

echo "Starting YouTube Music OAuth flow..."
echo ""

RESPONSE=$(curl -s -X POST "$HOST/streaming/accounts" \
  -H 'Content-Type: application/json' \
  -d "{\"display_name\":\"$DISPLAY_NAME\",\"client_id\":\"$CLIENT_ID\",\"client_secret\":\"$CLIENT_SECRET\"}")

DEVICE_CODE=$(echo "$RESPONSE" | jq -r '.device_code')
USER_CODE=$(echo "$RESPONSE" | jq -r '.user_code')
VERIFICATION_URL=$(echo "$RESPONSE" | jq -r '.verification_url')

if [[ "$DEVICE_CODE" == "null" || -z "$DEVICE_CODE" ]]; then
  echo "Failed to start auth flow. Server response:"
  echo "$RESPONSE" | jq .
  exit 1
fi

echo "1. Open this URL in your browser:"
echo "   $VERIFICATION_URL"
echo ""
echo "2. Enter this code when prompted:"
echo "   $USER_CODE"
echo ""
read -rp "Press Enter once you have authorized in the browser..."
echo ""

echo "Completing auth..."

RESULT=$(curl -s -X POST "$HOST/streaming/accounts" \
  -H 'Content-Type: application/json' \
  -d "{\"display_name\":\"$DISPLAY_NAME\",\"client_id\":\"$CLIENT_ID\",\"client_secret\":\"$CLIENT_SECRET\",\"device_code\":\"$DEVICE_CODE\"}")

if echo "$RESULT" | jq -e '.id' > /dev/null 2>&1; then
  echo "Account created successfully:"
  echo "$RESULT" | jq '{id: .id, display_name: .display_name, provider: .provider, auth_state: .auth_state}'
else
  echo "Something went wrong:"
  echo "$RESULT" | jq .
  exit 1
fi
