import { type QueryKey, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { useJobRefreshScheduler } from "./JobRefreshProvider";

const defaultDelaysMs = [3000, 10000] as const;

// Use delayed invalidation only after a mutation queues backend work whose visible
// results land after the request returns. Synchronous mutations should invalidate immediately.
export function useDelayedInvalidate(): (
  queryKeys: readonly QueryKey[],
  delaysMs?: readonly number[],
) => void {
  // Keep the query client hook here so callers still fail clearly when mounted
  // outside the application's QueryClientProvider.
  useQueryClient();
  const scheduleRefresh = useJobRefreshScheduler();

  return useCallback(
    (queryKeys: readonly QueryKey[], delaysMs: readonly number[] = defaultDelaysMs) => {
      scheduleRefresh(queryKeys, delaysMs);
    },
    [scheduleRefresh],
  );
}
