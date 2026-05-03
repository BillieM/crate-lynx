import { useQuery } from "@tanstack/react-query";

export type PlaylistTrackStatus = "linked" | "pending" | "unlinked";

export type PlaylistDetail = {
  account_id: number;
  cover_art_url: string | null;
  id: number;
  linked_count: number;
  name: string;
  pending_count: number;
  provider_playlist_id: string;
  synced_at: string | null;
  track_count: number;
  unlinked_count: number;
};

export type PlaylistTrack = {
  album: string | null;
  artist: string;
  duration_ms: number | null;
  final_link_id: number | null;
  id: number;
  local_track_id: number | null;
  position: number;
  proposal_id: number | null;
  provider_track_id: string;
  status: PlaylistTrackStatus;
  title: string;
};

export type PlaylistDetailResponse = {
  playlist: PlaylistDetail;
};

export type PlaylistTracksResponse = {
  tracks: PlaylistTrack[];
};

export const playlistQueryKeys = {
  all: ["playlists"] as const,
  detail: (playlistId: number | string) => ["playlists", playlistId, "detail"] as const,
  tracks: (playlistId: number | string) => ["playlists", playlistId, "tracks"] as const,
};

function hasPlaylistId(playlistId: number | string | null | undefined): playlistId is number | string {
  if (playlistId === null || playlistId === undefined) {
    return false;
  }

  return String(playlistId).trim().length > 0;
}

async function fetchJson<T>(input: RequestInfo | URL): Promise<T> {
  const response = await fetch(input);

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }

  return (await response.json()) as T;
}

export async function fetchPlaylistDetail(playlistId: number | string): Promise<PlaylistDetailResponse> {
  return fetchJson<PlaylistDetailResponse>(`/api/playlists/${encodeURIComponent(String(playlistId))}`);
}

export async function fetchPlaylistTracks(playlistId: number | string): Promise<PlaylistTracksResponse> {
  return fetchJson<PlaylistTracksResponse>(`/api/playlists/${encodeURIComponent(String(playlistId))}/tracks`);
}

export function usePlaylistDetailQuery(playlistId: number | string | null | undefined) {
  return useQuery({
    queryKey: hasPlaylistId(playlistId) ? playlistQueryKeys.detail(playlistId) : playlistQueryKeys.detail("idle"),
    queryFn: () => fetchPlaylistDetail(playlistId as number | string),
    enabled: hasPlaylistId(playlistId),
  });
}

export function usePlaylistTracksQuery(playlistId: number | string | null | undefined) {
  return useQuery({
    queryKey: hasPlaylistId(playlistId) ? playlistQueryKeys.tracks(playlistId) : playlistQueryKeys.tracks("idle"),
    queryFn: () => fetchPlaylistTracks(playlistId as number | string),
    enabled: hasPlaylistId(playlistId),
  });
}
