import { useMutation, useQuery } from "@tanstack/react-query";

import { ApiRequestError, endpoints, fetchJson, postJson } from "../../lib/api";

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

export type RematchLocalTrackResponse = {
  job_id: string;
  local_track_id: number;
};

export type RematchUnresolvedLocalTracksResponse = {
  job_id: string;
  statuses: ["unlinked", "pending"];
};

export type RescuedLocalTrack = {
  beets_id: number | null;
  file_path: string;
  id: number;
  library_root_rel_path: string | null;
  metadata: RescuedMetadata | null;
  rescue: MetadataRescueReport;
};

export type RescuedMetadata = {
  album: string | null;
  album_art_url: string | null;
  artist: string;
  title: string;
  year: number | null;
};

export type MetadataRescueStage = {
  detail: string;
  name: "metadata_fetch" | "file_tags" | "beets_catalogue" | "postgres_mirror" | "failed_attempt" | string;
  status: "succeeded" | "failed" | "skipped" | "not_applicable";
};

export type MetadataRescueReport = {
  completed: boolean;
  failed_attempt_id: number | null;
  partial_failure: boolean;
  stages: MetadataRescueStage[];
};

export class MetadataRescueRequestError extends ApiRequestError {
  result: RescuedLocalTrack | null;

  constructor(message: string, status: number, result: RescuedLocalTrack | null = null) {
    super(message, status);
    this.name = "MetadataRescueRequestError";
    this.result = result;
  }
}

export const localTrackQueryKeys = {
  all: ["local-tracks"] as const,
  detail: (localTrackId: number | string) => ["local-tracks", localTrackId, "detail"] as const,
};

export async function fetchLocalTrackDetail(localTrackId: number | string): Promise<LocalTrackDetail> {
  return fetchJson<LocalTrackDetail>(endpoints.api(`/local-tracks/${encodeURIComponent(String(localTrackId))}`));
}

export async function rematchLocalTrack(localTrackId: number | string): Promise<RematchLocalTrackResponse> {
  return postJson<RematchLocalTrackResponse>(
    endpoints.api(`/local-tracks/${encodeURIComponent(String(localTrackId))}/rematch`),
    {
      errorMessage: "Re-match request failed",
    },
  );
}

export async function rematchUnresolvedLocalTracks(): Promise<RematchUnresolvedLocalTracksResponse> {
  return postJson<RematchUnresolvedLocalTracksResponse>(endpoints.api("/local-tracks/rematch-unresolved"), {
    errorMessage: "Unresolved re-match request failed",
  });
}

export function useRematchUnresolvedLocalTracksMutation() {
  return useMutation({
    mutationFn: rematchUnresolvedLocalTracks,
  });
}

export async function rescueLocalTrackMetadata(
  localTrackId: number | string,
  failedAttemptId?: number | string | null,
): Promise<RescuedLocalTrack> {
  const baseUrl = endpoints.api(`/local-tracks/${encodeURIComponent(String(localTrackId))}/rescue`);
  const url =
    failedAttemptId === null || failedAttemptId === undefined
      ? baseUrl
      : `${baseUrl}?failed_attempt_id=${encodeURIComponent(String(failedAttemptId))}`;
  const response = await fetch(url, { method: "POST" });
  const payload = typeof response.json === "function" ? ((await response.json()) as unknown) : undefined;

  if (!response.ok) {
    const partialFailure = parseMetadataRescueFailure(payload);
    throw new MetadataRescueRequestError(
      partialFailure?.message ?? "Metadata rescue request failed",
      response.status,
      partialFailure?.result ?? null,
    );
  }

  return payload as RescuedLocalTrack;
}

function parseMetadataRescueFailure(payload: unknown): { message: string; result: RescuedLocalTrack } | null {
  if (!isRecord(payload) || !isRecord(payload.detail)) {
    return null;
  }
  const { message, result } = payload.detail;
  if (typeof message !== "string" || !isRescuedLocalTrack(result)) {
    return null;
  }
  return { message, result };
}

function isRescuedLocalTrack(value: unknown): value is RescuedLocalTrack {
  return (
    isRecord(value) &&
    typeof value.id === "number" &&
    typeof value.file_path === "string" &&
    isRecord(value.rescue) &&
    typeof value.rescue.completed === "boolean" &&
    typeof value.rescue.partial_failure === "boolean" &&
    Array.isArray(value.rescue.stages)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function useLocalTrackDetailQuery(localTrackId: number | string | null | undefined, enabled = true) {
  const hasLocalTrackId = localTrackId !== null && localTrackId !== undefined && localTrackId !== "";

  return useQuery({
    enabled: enabled && hasLocalTrackId,
    queryKey: hasLocalTrackId ? localTrackQueryKeys.detail(localTrackId) : localTrackQueryKeys.detail("idle"),
    queryFn: () => fetchLocalTrackDetail(localTrackId as number | string),
  });
}
