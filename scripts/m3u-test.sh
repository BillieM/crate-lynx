#!/bin/bash
# Test M3U generation (E07) against the running app.
# Usage: HOST=http://localhost:18101 ./m3u-test.sh
set -euo pipefail

HOST="${HOST:-http://192.168.0.203:18101}"

assert_status() {
  local label="$1"
  local expected="$2"
  local actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    echo "PASS $label (got $actual)"
  else
    echo "FAIL $label (expected $expected, got $actual)"
    exit 1
  fi
}

assert_header() {
  local label="$1"
  local pattern="$2"
  local headers="$3"
  if echo "$headers" | grep -qiF "$pattern"; then
    echo "PASS $label"
  else
    echo "FAIL $label (pattern '$pattern' not found in headers)"
    echo "$headers"
    exit 1
  fi
}

# ── 1. List playlists ─────────────────────────────────────────────────────────

echo "=== Streaming playlists ==="
PLAYLISTS_JSON=$(curl -s "$HOST/streaming/playlists")
echo "$PLAYLISTS_JSON" | jq .
PLAYLIST_COUNT=$(echo "$PLAYLISTS_JSON" | jq '.playlists | length')
echo "Total playlists: $PLAYLIST_COUNT"
echo ""

FIRST_PLAYLIST_ID=$(echo "$PLAYLISTS_JSON" | jq '.playlists[0].id // empty')

# ── 2. M3U export: structural tests ──────────────────────────────────────────

if [[ -z "$FIRST_PLAYLIST_ID" ]]; then
  echo "(No playlists — skipping M3U export structural tests)"
  echo ""
else
  echo "=== M3U export: GET /playlists/$FIRST_PLAYLIST_ID/m3u ==="

  FULL_RESPONSE=$(curl -s -D - "$HOST/playlists/$FIRST_PLAYLIST_ID/m3u" | tr -d '\r')
  HEADERS=$(echo "$FULL_RESPONSE" | awk 'NF==0{exit} {print}')
  BODY=$(echo "$FULL_RESPONSE" | awk 'found{print} /^$/{found=1}')

  HTTP=$(echo "$HEADERS" | head -1 | awk '{print $2}')
  assert_status "M3U export HTTP status" "200" "$HTTP"

  assert_header "Content-Type audio/x-mpegurl" "audio/x-mpegurl" "$HEADERS"
  assert_header "Content-Disposition attachment" "attachment" "$HEADERS"
  assert_header "Content-Disposition .m3u filename" ".m3u" "$HEADERS"

  FIRST_LINE=$(echo "$BODY" | head -1)
  if [[ "$FIRST_LINE" == "#EXTM3U" ]]; then
    echo "PASS M3U body starts with #EXTM3U"
  else
    echo "FAIL M3U body missing #EXTM3U header (got: $FIRST_LINE)"
    exit 1
  fi

  if echo "$BODY" | grep -qF "#EXTINF"; then
    echo "INFO: #EXTINF lines present (linked tracks found)"
    if echo "$BODY" | grep -qE '^#EXTINF:[0-9-]+,.+ - .+'; then
      echo "PASS #EXTINF format valid"
    else
      echo "FAIL #EXTINF lines present but format invalid"
      echo "$BODY"
      exit 1
    fi
  else
    echo "INFO: no #EXTINF lines (no final-linked tracks in this playlist)"
  fi

  echo "--- M3U body ---"
  echo "$BODY"
  echo ""
fi

# ── 3. 404 for non-existent playlist ─────────────────────────────────────────

echo "=== 404 tests ==="
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "$HOST/playlists/0/m3u")
assert_status "M3U for non-existent playlist (id=0)" "404" "$HTTP"
echo ""

# ── 4. Approve → verify M3U picks up new track ───────────────────────────────

ALL_PROPOSALS=$(curl -s "$HOST/api/proposals")
PENDING_PROPOSALS=$(echo "$ALL_PROPOSALS" | jq '[.proposals[] | select(.status == "pending")]')
PENDING_COUNT=$(echo "$PENDING_PROPOSALS" | jq 'length')

if [[ "$PENDING_COUNT" -eq 0 ]]; then
  echo "(No pending proposals — skipping approve/break M3U tests)"
else
  PROPOSAL_ID=$(echo "$PENDING_PROPOSALS" | jq '.[0].id')
  STREAMING_ARTIST=$(echo "$PENDING_PROPOSALS" | jq -r '.[0].streaming_artist')
  STREAMING_TITLE=$(echo "$PENDING_PROPOSALS" | jq -r '.[0].streaming_title')

  echo "=== Approve proposal $PROPOSAL_ID ($STREAMING_ARTIST - $STREAMING_TITLE) ==="
  HTTP=$(curl -s -o /tmp/m3u-approve.json -w "%{http_code}" \
    -X POST "$HOST/api/proposals/$PROPOSAL_ID/approve" \
    -H "Content-Type: application/json")
  assert_status "approve proposal" "201" "$HTTP"
  cat /tmp/m3u-approve.json | jq .
  FINAL_LINK_ID=$(cat /tmp/m3u-approve.json | jq '.final_link_id')
  echo ""

  # Scan all playlists for the newly approved track
  EXPECTED_EXTINF="${STREAMING_ARTIST} - ${STREAMING_TITLE}"
  FOUND_IN_PLAYLIST=""

  ALL_PLAYLIST_IDS=$(echo "$PLAYLISTS_JSON" | jq -r '.playlists[].id')
  for plid in $ALL_PLAYLIST_IDS; do
    M3U_BODY=$(curl -s "$HOST/playlists/$plid/m3u")
    if echo "$M3U_BODY" | grep -qF "$EXPECTED_EXTINF"; then
      FOUND_IN_PLAYLIST="$plid"
      TARGET_M3U_BODY="$M3U_BODY"
      break
    fi
  done

  if [[ -n "$FOUND_IN_PLAYLIST" ]]; then
    echo "PASS track '$EXPECTED_EXTINF' present in M3U for playlist $FOUND_IN_PLAYLIST"
    echo "--- M3U body ---"
    echo "$TARGET_M3U_BODY"
    echo ""
  else
    echo "INFO: track '$EXPECTED_EXTINF' not found in any playlist M3U"
    echo "      (streaming track has no playlist membership — approve API verified, M3U content check skipped)"
    echo ""
  fi

  # ── 5. Break link → verify track removed from M3U ────────────────────────

  echo "=== Break final link $FINAL_LINK_ID ==="
  HTTP=$(curl -s -o /tmp/m3u-break.json -w "%{http_code}" \
    -X DELETE "$HOST/api/final-links/$FINAL_LINK_ID")
  assert_status "break final link" "200" "$HTTP"
  cat /tmp/m3u-break.json | jq .
  echo ""

  if [[ -n "$FOUND_IN_PLAYLIST" ]]; then
    AFTER_BREAK=$(curl -s "$HOST/playlists/$FOUND_IN_PLAYLIST/m3u")
    if echo "$AFTER_BREAK" | grep -qF "$EXPECTED_EXTINF"; then
      echo "FAIL track '$EXPECTED_EXTINF' still present in M3U after break"
      echo "$AFTER_BREAK"
      exit 1
    else
      echo "PASS track '$EXPECTED_EXTINF' no longer in M3U after break"
    fi
    echo ""
  fi
fi

echo ""
echo "All assertions passed."
