import { type QueryClient, type QueryKey, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { endpoints, fetchJson, postJson } from "../../lib/api";
import type { components } from "../../lib/api-types";
import { invalidateQueryKeys } from "../../lib/queryInvalidation";
import { sonicQueryKeys } from "../sonic/queries";
import { trackMutationInvalidationKeys } from "../tracks/queries";

type ApiSchemas = components["schemas"];

export type LocalDedupeDecision = ApiSchemas["LocalDedupeDecisionResponse"];
export type LocalDedupeGroup = ApiSchemas["LocalDedupeGroupResponse"];
export type LocalDedupeQueueResponse = ApiSchemas["LocalDedupeQueueResponse"];
export type LocalDedupeResolveResponse = ApiSchemas["LocalDedupeResolveResponse"];
export type LocalDedupeSource = LocalDedupeGroup["source"];
export type LocalDedupeTrack = ApiSchemas["LocalDedupeTrackResponse"];
export type ResolveLocalDedupeGroupRequest = ApiSchemas["ResolveLocalDedupeGroupRequest"];

export const localDedupeQueryKeys = {
  all: ["local-dedupe"] as const,
  queue: () => ["local-dedupe", "queue"] as const,
};

export function localDedupeInvalidationKeys(): QueryKey[] {
  return [
    localDedupeQueryKeys.all,
    localDedupeQueryKeys.queue(),
    ...trackMutationInvalidationKeys(),
    sonicQueryKeys.all,
  ];
}

export async function invalidateLocalDedupeMutationQueries(queryClient: QueryClient): Promise<void> {
  await invalidateQueryKeys(queryClient, localDedupeInvalidationKeys());
}

export async function fetchLocalDedupeQueue(): Promise<LocalDedupeQueueResponse> {
  return fetchJson<LocalDedupeQueueResponse>(endpoints.api("/local-dedupe/queue"));
}

export async function resolveLocalDedupeGroup(
  groupKey: string,
  input: ResolveLocalDedupeGroupRequest,
): Promise<LocalDedupeResolveResponse> {
  return postJson<LocalDedupeResolveResponse>(
    endpoints.api(`/local-dedupe/groups/${encodeURIComponent(groupKey)}/resolve`),
    {
      body: input,
      errorMessage: "Local dedupe resolve request failed",
    },
  );
}

export async function dismissLocalDedupeGroup(groupKey: string): Promise<LocalDedupeDecision> {
  return postJson<LocalDedupeDecision>(
    endpoints.api(`/local-dedupe/groups/${encodeURIComponent(groupKey)}/dismiss`),
    {
      errorMessage: "Local dedupe dismiss request failed",
    },
  );
}

export function useLocalDedupeQueueQuery() {
  return useQuery({
    queryKey: localDedupeQueryKeys.queue(),
    queryFn: fetchLocalDedupeQueue,
  });
}

export function useResolveLocalDedupeGroupMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ groupKey, input }: { groupKey: string; input: ResolveLocalDedupeGroupRequest }) =>
      resolveLocalDedupeGroup(groupKey, input),
    onSuccess: () => invalidateLocalDedupeMutationQueries(queryClient),
  });
}

export function useDismissLocalDedupeGroupMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: dismissLocalDedupeGroup,
    onSuccess: () => invalidateLocalDedupeMutationQueries(queryClient),
  });
}
