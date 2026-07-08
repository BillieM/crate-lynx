#!/bin/bash
# Copy a local track file into the app container's ingestion folder.
# Usage: ./ingest-track.sh /path/to/track.flac
set -euo pipefail

CONTAINER="${CONTAINER:-crate-lynx-app-1}"
INGESTION_CONTAINER_DIR="${INGESTION_CONTAINER_DIR:-/nas/cratelynx/music-in}"

if [[ -z "${1:-}" ]]; then
  echo "Usage: $0 /path/to/track.flac"
  exit 1
fi

SRC="$1"
FILENAME=$(basename "$SRC")

docker cp "$SRC" "$CONTAINER:$INGESTION_CONTAINER_DIR/$FILENAME"
echo "Copied $FILENAME to $CONTAINER:$INGESTION_CONTAINER_DIR/$FILENAME"
