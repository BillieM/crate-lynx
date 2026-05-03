import type { PlaylistTrack, PlaylistTrackStatus } from "./queries";

export type PlaylistTrackFilter = "all" | PlaylistTrackStatus;

export function filterPlaylistTracks(tracks: PlaylistTrack[], filter: PlaylistTrackFilter) {
  if (filter === "all") {
    return tracks;
  }

  return tracks.filter((track) => track.status === filter);
}

export function getPlaylistTrackFilterCounts(tracks: PlaylistTrack[]): Record<PlaylistTrackFilter, number> {
  return tracks.reduce<Record<PlaylistTrackFilter, number>>(
    (counts, track) => {
      counts.all += 1;
      counts[track.status] += 1;
      return counts;
    },
    {
      all: 0,
      linked: 0,
      pending: 0,
      unlinked: 0,
    },
  );
}
