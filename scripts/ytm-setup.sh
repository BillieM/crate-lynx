#!/bin/bash
# Walk through getting YouTube Music browser headers and saving them to the app.
set -euo pipefail

HOST="${HOST:-http://192.168.0.203:18101}"

echo "To get your browser headers:"
echo "  1. Open https://music.youtube.com in your browser and log in"
echo "  2. Open DevTools (F12), go to Network tab, and filter by 'Fetch/XHR'"
echo "  3. Reload the page, then find a POST request to music.youtube.com/youtubei/v1/"
echo "     (e.g. 'browse', 'search', or 'get_search_suggestions')"
echo "  4. Right-click that request > Copy > Copy as cURL"
echo ""
echo "  NOTE: Must be a POST/XHR request — static assets won't have auth cookies"
echo ""
read -rp "Press Enter once you've copied the cURL..."

RAW_CURL=$(pbpaste)

HEADERS=$(echo "$RAW_CURL" | python3 -c "
import sys, json, re
raw = sys.stdin.read()
headers = {}
for m in re.finditer(r\"-H '([^:]+): ([^']+)'\", raw):
    headers[m.group(1).lower()] = m.group(2)
# Chrome DevTools uses -b for cookies instead of -H 'cookie: ...'
cookie_b = re.search(r\"-b '([^']+)'\", raw)
if cookie_b and 'cookie' not in headers:
    headers['cookie'] = cookie_b.group(1)
print(json.dumps(headers))
")

if [[ -z "$HEADERS" || "$HEADERS" == "{}" ]]; then
  echo "Error: no headers parsed — make sure you used Copy > Copy as cURL from DevTools"
  exit 1
fi

if ! echo "$HEADERS" | python3 -c "import sys, json; h = json.load(sys.stdin); c = h.get('cookie', ''); exit(0 if '__Secure-3PAPISID' in c else 1)"; then
  echo "Error: cookie header is missing __Secure-3PAPISID — you likely copied a static asset request."
  echo "Go back to DevTools, filter by Fetch/XHR, and copy a POST request to youtubei/v1/"
  exit 1
fi

read -rp "Display name for this account: " DISPLAY_NAME

echo "Saving account..."

TMPFILE=$(mktemp)
PAYLOAD=$(jq -n --arg name "$DISPLAY_NAME" --argjson headers "$HEADERS" \
  '{display_name: $name, browser_headers: $headers}')

HTTP_CODE=$(curl -s -o "$TMPFILE" -w "%{http_code}" -X POST "$HOST/api/streaming/accounts" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")
BODY=$(cat "$TMPFILE")
rm "$TMPFILE"

if [[ "$HTTP_CODE" == "201" ]]; then
  echo "Account created:"
  echo "$BODY" | jq '{id: .id, display_name: .display_name, auth_state: .auth_state}'
else
  echo "Failed (HTTP $HTTP_CODE):"
  echo "$BODY" | jq .
  exit 1
fi
