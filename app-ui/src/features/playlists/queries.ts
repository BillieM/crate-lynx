import { useQuery } from "@tanstack/react-query";

export type PlaylistTrackStatus = "linked" | "pending" | "unlinked";
export type LinkProposalConfidenceBand = "high" | "medium" | "low";

export type PlaylistDetail = {
  account_id: number;
  cover_art_url: string | null;
  id: number;
  last_sync_error: string | null;
  last_sync_error_at: string | null;
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

export type LinkProposal = {
  confidence_band: LinkProposalConfidenceBand;
  id: number;
  local_file_path: string;
  local_track_id: number;
  match_method: string;
  rejected_at: string | null;
  score: number;
  status: string;
  streaming_album: string | null;
  streaming_artist: string;
  streaming_title: string;
  streaming_track_id: number;
};

export type LinkProposalsResponse = {
  proposals: LinkProposal[];
};

export type ApproveLinkProposalResponse = {
  final_link_id: number;
  proposal_id: number;
  status: "approved";
};

export type RejectLinkProposalResponse = {
  proposal_id: number;
  rejected_at: string;
  status: "rejected";
};

export type LinkProposalListFilters = {
  confidenceBand?: LinkProposalConfidenceBand | null;
};

export type StreamingSyncResponse = {
  account_id: number;
  job_id: string;
};

export type PlaylistSyncResponse = {
  playlist_id: number;
  job_id: string;
};

export const playlistQueryKeys = {
  all: ["playlists"] as const,
  config: () => ["playlists", "config"] as const,
  detail: (playlistId: number | string) => ["playlists", playlistId, "detail"] as const,
  list: () => ["playlists", "list"] as const,
  proposals: (filters: LinkProposalListFilters = {}) =>
    ["playlists", "proposals", { confidenceBand: filters.confidenceBand ?? null }] as const,
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

export async function refreshStreamingAccountMetadata(accountId: number | string): Promise<StreamingSyncResponse> {
  const response = await fetch(`/api/streaming/accounts/${encodeURIComponent(String(accountId))}/refresh-metadata`, {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(`Metadata refresh request failed with status ${response.status}`);
  }

  return (await response.json()) as StreamingSyncResponse;
}

export async function syncStreamingAccount(accountId: number | string): Promise<StreamingSyncResponse> {
  const response = await fetch(`/api/streaming/accounts/${encodeURIComponent(String(accountId))}/sync`, {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(`Sync request failed with status ${response.status}`);
  }

  return (await response.json()) as StreamingSyncResponse;
}

export async function syncStreamingPlaylist(playlistId: number | string): Promise<PlaylistSyncResponse> {
  const response = await fetch(`/api/streaming/playlists/${encodeURIComponent(String(playlistId))}/sync`, {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(`Playlist sync request failed with status ${response.status}`);
  }

  return (await response.json()) as PlaylistSyncResponse;
}

export async function fetchPlaylistTracks(playlistId: number | string): Promise<PlaylistTracksResponse> {
  return fetchJson<PlaylistTracksResponse>(`/api/playlists/${encodeURIComponent(String(playlistId))}/tracks`);
}

export async function fetchLinkProposals(filters: LinkProposalListFilters = {}): Promise<LinkProposalsResponse> {
  const params = new URLSearchParams();

  if (filters.confidenceBand) {
    params.set("band", filters.confidenceBand);
  }

  const queryString = params.toString();
  return fetchJson<LinkProposalsResponse>(`/api/proposals${queryString ? `?${queryString}` : ""}`);
}

export async function approveLinkProposal(proposalId: number | string): Promise<ApproveLinkProposalResponse> {
  const response = await fetch(`/api/proposals/${encodeURIComponent(String(proposalId))}/approve`, {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(`Proposal approve request failed with status ${response.status}`);
  }

  return (await response.json()) as ApproveLinkProposalResponse;
}

export async function rejectLinkProposal(proposalId: number | string): Promise<RejectLinkProposalResponse> {
  const response = await fetch(`/api/proposals/${encodeURIComponent(String(proposalId))}/reject`, {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(`Proposal reject request failed with status ${response.status}`);
  }

  return (await response.json()) as RejectLinkProposalResponse;
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

export function useLinkProposalsQuery(filters: LinkProposalListFilters = {}) {
  return useQuery({
    queryKey: playlistQueryKeys.proposals(filters),
    queryFn: () => fetchLinkProposals(filters),
  });
}
