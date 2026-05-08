import { type QueryClient, type QueryKey, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { endpoints, fetchJson, patchJson, postJson } from "../../lib/api";
import type { components } from "../../lib/api-types";
import { invalidateQueryKeys } from "../../lib/queryInvalidation";
import {
  playlistCollectionJobInvalidationKeys,
  playlistConfigurationInvalidationKeys,
  playlistSyncJobInvalidationKeys,
} from "../playlists/queries";

type ApiSchemas = components["schemas"];

export type StreamingAccount = ApiSchemas["StreamingAccountResponse"];
export type StreamingAccountsResponse = ApiSchemas["StreamingAccountsResponse"];
export type CreateStreamingAccountInput = ApiSchemas["CreateStreamingAccountRequest"];
export type RefreshStreamingAccountAuthInput = ApiSchemas["UpdateStreamingAccountAuthRequest"] & {
  accountId: number | string;
};

const streamingAccountSchema: z.ZodType<StreamingAccount> = z.object({
  auth_error: z.string().nullable(),
  auth_error_at: z.string().nullable(),
  auth_state: z.string(),
  created_at: z.string(),
  display_name: z.string(),
  id: z.number(),
  provider: z.string(),
  updated_at: z.string(),
});

const streamingAccountsResponseSchema: z.ZodType<StreamingAccountsResponse> = z.object({
  accounts: z.array(streamingAccountSchema),
});

export const streamingAccountQueryKeys = {
  all: ["streaming-accounts"] as const,
  list: () => ["streaming-accounts", "list"] as const,
};

export function streamingAccountInvalidationKeys(): QueryKey[] {
  return [streamingAccountQueryKeys.list()];
}

export function streamingAccountMutationInvalidationKeys(): QueryKey[] {
  return [...streamingAccountInvalidationKeys(), ...playlistConfigurationInvalidationKeys()];
}

export function streamingAccountCollectionJobInvalidationKeys(): QueryKey[] {
  return [...streamingAccountInvalidationKeys(), ...playlistCollectionJobInvalidationKeys()];
}

export function streamingAccountPlaylistSyncJobInvalidationKeys(
  playlistIds: readonly (number | string)[],
): QueryKey[] {
  return [...streamingAccountInvalidationKeys(), ...playlistSyncJobInvalidationKeys(playlistIds)];
}

export async function invalidateStreamingAccountMutationQueries(queryClient: QueryClient): Promise<void> {
  await invalidateQueryKeys(queryClient, streamingAccountMutationInvalidationKeys());
}

export async function fetchStreamingAccounts(): Promise<StreamingAccountsResponse> {
  return fetchJson(endpoints.api("/streaming/accounts"), streamingAccountsResponseSchema);
}

export async function createStreamingAccount({
  browser_headers,
  display_name,
}: CreateStreamingAccountInput): Promise<StreamingAccount> {
  return postJson(endpoints.api("/streaming/accounts"), {
    body: { display_name, browser_headers },
    errorMessage: "Streaming account create request failed",
    schema: streamingAccountSchema,
  });
}

export async function refreshStreamingAccountAuth({
  accountId,
  browser_headers,
}: RefreshStreamingAccountAuthInput): Promise<StreamingAccount> {
  return patchJson(endpoints.api(`/streaming/accounts/${encodeURIComponent(String(accountId))}/auth`), {
    body: { browser_headers },
    errorMessage: "Streaming account auth refresh request failed",
    schema: streamingAccountSchema,
  });
}

export function useStreamingAccountsQuery() {
  return useQuery({
    queryKey: streamingAccountQueryKeys.list(),
    queryFn: fetchStreamingAccounts,
  });
}

export function useCreateStreamingAccountMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createStreamingAccount,
    onSuccess: () => invalidateStreamingAccountMutationQueries(queryClient),
  });
}

export function useRefreshStreamingAccountAuthMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: refreshStreamingAccountAuth,
    onSuccess: () => invalidateStreamingAccountMutationQueries(queryClient),
  });
}
