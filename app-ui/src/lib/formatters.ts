export function formatDuration(durationMs: number | null) {
  if (durationMs === null || durationMs < 0) {
    return "Unknown";
  }

  const totalSeconds = Math.floor(durationMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function formatPlaylistTimestamp(timestamp: string | null) {
  if (!timestamp) {
    return "Not synced yet";
  }

  return timestamp.replace("T", " ").replace(/(?:\.\d+)?Z?$/, "");
}

export function getLocalTrackLabel(localTrack: { local_file_path: string }) {
  return localTrack.local_file_path.split("/").pop() || localTrack.local_file_path;
}

export function getMatchMethodLabel(matchMethod: string) {
  const normalizedMethod = matchMethod.toLowerCase();

  if (normalizedMethod === "isrc") {
    return "ISRC";
  }

  if (normalizedMethod === "tag") {
    return "Tag";
  }

  return matchMethod;
}
