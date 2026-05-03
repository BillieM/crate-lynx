#!/bin/bash
# Test link proposal & approval API (E06) against the running app.
# Usage: HOST=http://localhost:18101 ./links-test.sh [proposal_id]
set -euo pipefail

HOST="${HOST:-http://192.168.0.203:18101}"
PROPOSAL_ID="${1:-}"

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

# ── 1. List & filter ─────────────────────────────────────────────────────────

echo "=== Proposals (all) ==="
ALL=$(curl -s "$HOST/api/proposals")
echo "$ALL" | jq .
TOTAL=$(echo "$ALL" | jq '.proposals | length')
echo "Total proposals: $TOTAL"
echo ""

echo "--- Band breakdown ---"
echo "$ALL" | jq -r '
  .proposals
  | group_by(.confidence_band)[]
  | "\(.[0].confidence_band): \(length)"
'
echo ""

for BAND in high medium low; do
  COUNT=$(curl -s "$HOST/api/proposals?band=$BAND" | jq '.proposals | length')
  echo "  ?band=$BAND → $COUNT proposals"
done
echo ""

# ── Pick pending proposals ────────────────────────────────────────────────────

PENDING_IDS=$(echo "$ALL" | jq -r '[.proposals[] | select(.status == "pending") | .id] | @json')
PENDING_COUNT=$(echo "$PENDING_IDS" | jq 'length')

if [[ "$PENDING_COUNT" -eq 0 ]]; then
  echo "(No pending proposals — skipping lifecycle tests)"
else
  if [[ -n "$PROPOSAL_ID" ]]; then
    FIRST_ID="$PROPOSAL_ID"
  else
    FIRST_ID=$(echo "$PENDING_IDS" | jq '.[0]')
  fi

  FIRST_LOCAL_TRACK_ID=$(echo "$ALL" | jq --argjson id "$FIRST_ID" \
    '.proposals[] | select(.id == $id) | .local_track_id')

  # Pick a second pending proposal for the reject scenario (different from first)
  SECOND_ID=$(echo "$PENDING_IDS" | jq --argjson first "$FIRST_ID" \
    'map(select(. != $first)) | .[0] // empty')

  # ── 2. Approve → break → rejected-pair guard ─────────────────────────────

  echo "=== Approve proposal $FIRST_ID ==="
  HTTP=$(curl -s -o /tmp/links-approve.json -w "%{http_code}" \
    -X POST "$HOST/api/proposals/$FIRST_ID/approve" \
    -H "Content-Type: application/json")
  assert_status "approve proposal" "201" "$HTTP"
  cat /tmp/links-approve.json | jq .
  FINAL_LINK_ID=$(cat /tmp/links-approve.json | jq '.final_link_id')
  echo ""

  echo "=== Break final link $FINAL_LINK_ID ==="
  HTTP=$(curl -s -o /tmp/links-break.json -w "%{http_code}" \
    -X DELETE "$HOST/api/final-links/$FINAL_LINK_ID")
  assert_status "break final link" "200" "$HTTP"
  cat /tmp/links-break.json | jq .
  echo ""

  echo "=== Rejected-pair guard: re-approve proposal $FIRST_ID (expect 409) ==="
  HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$HOST/api/proposals/$FIRST_ID/approve" \
    -H "Content-Type: application/json")
  assert_status "rejected-pair guard (approve after break)" "409" "$HTTP"
  echo ""

  # ── 3. Reject → rejected-pair guard ──────────────────────────────────────

  if [[ -n "$SECOND_ID" ]]; then
    echo "=== Reject proposal $SECOND_ID ==="
    HTTP=$(curl -s -o /tmp/links-reject.json -w "%{http_code}" \
      -X POST "$HOST/api/proposals/$SECOND_ID/reject" \
      -H "Content-Type: application/json")
    assert_status "reject proposal" "200" "$HTTP"
    cat /tmp/links-reject.json | jq .
    echo ""

    echo "=== Rejected-pair guard: approve rejected proposal $SECOND_ID (expect 409) ==="
    HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
      -X POST "$HOST/api/proposals/$SECOND_ID/approve" \
      -H "Content-Type: application/json")
    assert_status "rejected-pair guard (approve after reject)" "409" "$HTTP"
    echo ""
  else
    echo "(Only one pending proposal available — skipping reject scenario)"
    echo ""
  fi

  # ── 4. Rematch ────────────────────────────────────────────────────────────

  echo "=== Rematch local track $FIRST_LOCAL_TRACK_ID ==="
  HTTP=$(curl -s -o /tmp/links-rematch.json -w "%{http_code}" \
    -X POST "$HOST/local-tracks/$FIRST_LOCAL_TRACK_ID/rematch" \
    -H "Content-Type: application/json")
  assert_status "rematch local track" "202" "$HTTP"
  cat /tmp/links-rematch.json | jq .
  echo ""
fi

# ── 5. 404 error cases ────────────────────────────────────────────────────────

echo "=== 404 tests ==="

HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "$HOST/api/proposals/0/approve" -H "Content-Type: application/json")
assert_status "approve non-existent proposal" "404" "$HTTP"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "$HOST/api/proposals/0/reject" -H "Content-Type: application/json")
assert_status "reject non-existent proposal" "404" "$HTTP"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
  -X DELETE "$HOST/api/final-links/0")
assert_status "break non-existent final link" "404" "$HTTP"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "$HOST/local-tracks/0/rematch" -H "Content-Type: application/json")
assert_status "rematch non-existent track" "404" "$HTTP"

echo ""
echo "All assertions passed."
