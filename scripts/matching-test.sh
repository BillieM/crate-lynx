#!/bin/bash
# Test matching pipeline endpoints against the running app.
# Usage: HOST=http://localhost:8000 ./matching-test.sh [local_track_id]
set -euo pipefail

HOST="${HOST:-http://192.168.0.203:18101}"
LOCAL_TRACK_ID="${1:-}"
MATCH_WAIT="${MATCH_WAIT:-8}"

echo "=== Matching Status ==="
STATUS=$(curl -s "$HOST/matching/status")
echo "$STATUS" | jq .
echo ""

echo "--- Suggestions by confidence band ---"
echo "$STATUS" | jq -r '
  .suggestions
  | group_by(.confidence_band)[]
  | "\(.[0].confidence_band): \(length)"
'
echo ""

if [[ -z "$LOCAL_TRACK_ID" ]]; then
  LOCAL_TRACK_ID=$(echo "$STATUS" | jq -r '.suggestions[0].local_track_id // empty')
fi

if [[ -z "$LOCAL_TRACK_ID" ]]; then
  echo "No local_track_id available — pass one as an argument or ensure suggestions exist."
  echo "Skipping trigger and poll tests."
else
  echo "=== Trigger matching for track $LOCAL_TRACK_ID ==="
  TRIGGER=$(curl -s -X POST "$HOST/matching/tracks/$LOCAL_TRACK_ID/run" \
    -H "Content-Type: application/json")
  echo "$TRIGGER" | jq .
  JOB_ID=$(echo "$TRIGGER" | jq -r '.job_id')
  echo ""
  echo "Job enqueued: $JOB_ID"
  echo "Waiting ${MATCH_WAIT}s for job to complete..."
  sleep "$MATCH_WAIT"

  echo ""
  echo "=== Updated suggestions for track $LOCAL_TRACK_ID ==="
  curl -s "$HOST/matching/status" | jq --argjson id "$LOCAL_TRACK_ID" \
    '[.suggestions[] | select(.local_track_id == $id)]'
  echo ""
fi

echo "=== 404 test: trigger matching for non-existent track (id=0) ==="
STATUS_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$HOST/matching/tracks/0/run" \
  -H "Content-Type: application/json")
if [[ "$STATUS_CODE" == "404" ]]; then
  echo "PASS (got 404)"
else
  echo "FAIL (expected 404, got $STATUS_CODE)"
  exit 1
fi
