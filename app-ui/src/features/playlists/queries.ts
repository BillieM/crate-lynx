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

export type StreamingPlaylist = {
  account_id: number;
  id: number;
  provider_playlist_id: string;
  synced_at: string | null;
  title: string;
  track_count: number;
};

export type StreamingPlaylistConfig = StreamingPlaylist & {
  last_sync_error: string | null;
  last_sync_error_at: string | null;
  selected_for_sync: boolean;
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

export type StreamingPlaylistsResponse = {
  playlists: StreamingPlaylist[];
};

export type StreamingPlaylistConfigResponse = {
  playlists: StreamingPlaylistConfig[];
};

export type UpdateStreamingPlaylistConfigInput = {
  playlistId: number | string;
  selected_for_sync: boolean;
};

export type PlaylistTracksResponse = {
  tracks: PlaylistTrack[];
};

export type PlaylistM3uExport = {
  blob: Blob;
  filename: string;
};

export const playlistQueryKeys = {
  all: ["playlists"] as const,
  config: () => ["playlists", "config"] as const,
  detail: (playlistId: number | string) => ["playlists", playlistId, "detail"] as const,
  list: () => ["playlists", "list"] as const,
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

function getFilenameFromContentDisposition(contentDisposition: string | null) {
  const fallbackFilename = "playlist.m3u";

  if (!contentDisposition) {
    return fallbackFilename;
  }

  const filenameMatch = /filename="?(?<filename>[^";]+)"?/i.exec(contentDisposition);
  return filenameMatch?.groups?.filename ?? fallbackFilename;
}

export async function fetchPlaylistDetail(playlistId: number | string): Promise<PlaylistDetailResponse> {
  return fetchJson<PlaylistDetailResponse>(`/api/playlists/${encodeURIComponent(String(playlistId))}`);
}

export async function fetchStreamingPlaylists(): Promise<StreamingPlaylistsResponse> {
  return fetchJson<StreamingPlaylistsResponse>("/api/streaming/playlists");
}

export async function fetchStreamingPlaylistConfig(): Promise<StreamingPlaylistConfigResponse> {
  return fetchJson<StreamingPlaylistConfigResponse>("/api/streaming/playlists/config");
}

export async function updateStreamingPlaylistConfig({
  playlistId,
  selected_for_sync,
}: UpdateStreamingPlaylistConfigInput): Promise<StreamingPlaylistConfig> {
  const response = await fetch(`/api/streaming/playlists/${encodeURIComponent(String(playlistId))}`, {
    body: JSON.stringify({ selected_for_sync }),
    headers: {
      "Content-Type": "application/json",
    },
    method: "PATCH",
  });

  if (!response.ok) {
    throw new Error(`Playlist update request failed with status ${response.status}`);
  }

  return (await response.json()) as StreamingPlaylistConfig;
}

export async function fetchPlaylistTracks(playlistId: number | string): Promise<PlaylistTracksResponse> {
  return fetchJson<PlaylistTracksResponse>(`/api/playlists/${encodeURIComponent(String(playlistId))}/tracks`);
}

export async function exportPlaylistM3u(playlistId: number | string): Promise<PlaylistM3uExport> {
  const response = await fetch(`/api/playlists/${encodeURIComponent(String(playlistId))}/m3u`);

  if (!response.ok) {
    throw new Error(`M3U export request failed with status ${response.status}`);
  }

  return {
    blob: await response.blob(),
    filename: getFilenameFromContentDisposition(response.headers.get("Content-Disposition")),
  };
}

export function usePlaylistDetailQuery(playlistId: number | string | null | undefined) {
  return useQuery({
    queryKey: hasPlaylistId(playlistId) ? playlistQueryKeys.detail(playlistId) : playlistQueryKeys.detail("idle"),
    queryFn: () => fetchPlaylistDetail(playlistId as number | string),
    enabled: hasPlaylistId(playlistId),
  });
}

export function useStreamingPlaylistsQuery() {
  return useQuery({
    queryKey: playlistQueryKeys.list(),
    queryFn: fetchStreamingPlaylists,
  });
}

export function useStreamingPlaylistConfigQuery() {
  return useQuery({
    queryKey: playlistQueryKeys.config(),
    queryFn: fetchStreamingPlaylistConfig,
  });
}

export function usePlaylistTracksQuery(playlistId: number | string | null | undefined) {
  return useQuery({
    queryKey: hasPlaylistId(playlistId) ? playlistQueryKeys.tracks(playlistId) : playlistQueryKeys.tracks("idle"),
    queryFn: () => fetchPlaylistTracks(playlistId as number | string),
    enabled: hasPlaylistId(playlistId),
  });
}
