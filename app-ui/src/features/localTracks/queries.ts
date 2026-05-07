import { useQuery } from "@tanstack/react-query";

import { endpoints, fetchJson } from "../../lib/api";

export type LocalTrackFinalLink = {
  approved_at: string;
  id: number;
  streaming_track_id: number;
};

export type LocalTrackSuggestion = {
  created_at: string;
  id: number;
  match_method: string;
  score: number;
  status: string;
  streaming_track_id: number;
};

export type LocalTrackFailedIngestionAttempt = {
  failed_at: string;
  failure_reason: string;
  filename: string;
  id: number;
  source_path: string;
};

export type LocalTrackDetail = {
  failed_ingestion_attempts: LocalTrackFailedIngestionAttempt[];
  file_path: string;
  final_link: LocalTrackFinalLink | null;
  id: number;
  library_root_rel_path: string;
  link_status: "linked" | "pending" | "unlinked" | string;
  pending_suggestions: LocalTrackSuggestion[];
};

export const localTrackQueryKeys = {
  all: ["local-tracks"] as const,
  detail: (localTrackId: number | string) => ["local-tracks", localTrackId, "detail"] as const,
};

export async function fetchLocalTrackDetail(localTrackId: number | string): Promise<LocalTrackDetail> {
  return fetchJson<LocalTrackDetail>(endpoints.api(`/local-tracks/${encodeURIComponent(String(localTrackId))}`));
}

export function useLocalTrackDetailQuery(localTrackId: number | string | null | undefined, enabled = true) {
  const hasLocalTrackId = localTrackId !== null && localTrackId !== undefined && localTrackId !== "";

  return useQuery({
    enabled: enabled && hasLocalTrackId,
    queryKey: hasLocalTrackId ? localTrackQueryKeys.detail(localTrackId) : localTrackQueryKeys.detail("idle"),
    queryFn: () => fetchLocalTrackDetail(localTrackId as number | string),
  });
}
