import { type QueryClient, type QueryKey, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteJson, endpoints, fetchJson, postJson } from "../../lib/api";
import { invalidateQueryKeys } from "../../lib/queryInvalidation";

export type IngestFolder = {
  id: number;
  path: string;
};

export type GeneralSettingsResponse = {
  ingest_folders: IngestFolder[];
};

export type CreateIngestFolderInput = {
  path: string;
};

export const settingsQueryKeys = {
  all: ["settings"] as const,
  general: () => ["settings", "general"] as const,
  ingestFolders: () => ["settings", "ingest-folders"] as const,
};

export function settingsInvalidationKeys(): QueryKey[] {
  return [settingsQueryKeys.general(), settingsQueryKeys.ingestFolders()];
}

export async function invalidateSettingsQueries(queryClient: QueryClient): Promise<void> {
  await invalidateQueryKeys(queryClient, settingsInvalidationKeys());
}

export async function fetchGeneralSettings(): Promise<GeneralSettingsResponse> {
  return fetchJson<GeneralSettingsResponse>(endpoints.api("/settings/general"));
}

export async function createIngestFolder({ path }: CreateIngestFolderInput): Promise<IngestFolder> {
  return postJson<IngestFolder>(endpoints.api("/settings/ingest-folders"), {
    body: { path },
    errorMessage: "Ingest folder create request failed",
  });
}

export async function deleteIngestFolder(folderId: number | string): Promise<void> {
  await deleteJson<void>(endpoints.api(`/settings/ingest-folders/${encodeURIComponent(String(folderId))}`), {
    errorMessage: "Ingest folder delete request failed",
  });
}

export function useGeneralSettingsQuery() {
  return useQuery({
    queryKey: settingsQueryKeys.general(),
    queryFn: fetchGeneralSettings,
  });
}

export function useCreateIngestFolderMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createIngestFolder,
    onSuccess: () => invalidateSettingsQueries(queryClient),
  });
}

export function useDeleteIngestFolderMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteIngestFolder,
    onSuccess: () => invalidateSettingsQueries(queryClient),
  });
}
