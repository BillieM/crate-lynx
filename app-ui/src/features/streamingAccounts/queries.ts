import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { endpoints, fetchJson } from "../../lib/api";
import { playlistQueryKeys } from "../playlists/queries";

export type StreamingAccount = {
  auth_error: string | null;
  auth_error_at: string | null;
  auth_state: string;
  created_at: string;
  display_name: string;
  id: number;
  provider: string;
  updated_at: string;
};

export type StreamingAccountsResponse = {
  accounts: StreamingAccount[];
};

export type CreateStreamingAccountInput = {
  browser_headers: Record<string, unknown>;
  display_name: string;
};

export type RefreshStreamingAccountAuthInput = {
  accountId: number | string;
  browser_headers: Record<string, unknown>;
};

export const streamingAccountQueryKeys = {
  all: ["streaming-accounts"] as const,
  list: () => ["streaming-accounts", "list"] as const,
};

function invalidateStreamingAccountMutationQueries(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: streamingAccountQueryKeys.list() });
  void queryClient.invalidateQueries({ queryKey: playlistQueryKeys.list() });
  void queryClient.invalidateQueries({ queryKey: playlistQueryKeys.config() });
}

export async function fetchStreamingAccounts(): Promise<StreamingAccountsResponse> {
  return fetchJson<StreamingAccountsResponse>(endpoints.api("/streaming/accounts"));
}

export async function createStreamingAccount({
  browser_headers,
  display_name,
}: CreateStreamingAccountInput): Promise<StreamingAccount> {
  const response = await fetch("/api/streaming/accounts", {
    body: JSON.stringify({ display_name, browser_headers }),
    headers: {
      "Content-Type": "application/json",
    },
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(`Streaming account create request failed with status ${response.status}`);
  }

  return (await response.json()) as StreamingAccount;
}

export async function refreshStreamingAccountAuth({
  accountId,
  browser_headers,
}: RefreshStreamingAccountAuthInput): Promise<StreamingAccount> {
  const response = await fetch(`/api/streaming/accounts/${encodeURIComponent(String(accountId))}/auth`, {
    body: JSON.stringify({ browser_headers }),
    headers: {
      "Content-Type": "application/json",
    },
    method: "PATCH",
  });

  if (!response.ok) {
    throw new Error(`Streaming account auth refresh request failed with status ${response.status}`);
  }

  return (await response.json()) as StreamingAccount;
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
    onSuccess: () => {
      invalidateStreamingAccountMutationQueries(queryClient);
    },
  });
}

export function useRefreshStreamingAccountAuthMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: refreshStreamingAccountAuth,
    onSuccess: () => {
      invalidateStreamingAccountMutationQueries(queryClient);
    },
  });
}
