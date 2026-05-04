import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

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

async function fetchJson<T>(input: RequestInfo | URL): Promise<T> {
  const response = await fetch(input);

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }

  return (await response.json()) as T;
}

function invalidateSettingsQueries(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: settingsQueryKeys.general() });
  void queryClient.invalidateQueries({ queryKey: settingsQueryKeys.ingestFolders() });
}

export async function fetchGeneralSettings(): Promise<GeneralSettingsResponse> {
  return fetchJson<GeneralSettingsResponse>("/api/settings/general");
}

export async function createIngestFolder({ path }: CreateIngestFolderInput): Promise<IngestFolder> {
  const response = await fetch("/api/settings/ingest-folders", {
    body: JSON.stringify({ path }),
    headers: {
      "Content-Type": "application/json",
    },
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(`Ingest folder create request failed with status ${response.status}`);
  }

  return (await response.json()) as IngestFolder;
}

export async function deleteIngestFolder(folderId: number | string): Promise<void> {
  const response = await fetch(`/api/settings/ingest-folders/${encodeURIComponent(String(folderId))}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    throw new Error(`Ingest folder delete request failed with status ${response.status}`);
  }
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
    onSuccess: () => {
      invalidateSettingsQueries(queryClient);
    },
  });
}

export function useDeleteIngestFolderMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteIngestFolder,
    onSuccess: () => {
      invalidateSettingsQueries(queryClient);
    },
  });
}
