import { type QueryKey, useQueryClient } from "@tanstack/react-query";
import { createContext, type PropsWithChildren, useCallback, useContext, useEffect, useRef } from "react";

type JobRefreshScheduler = (queryKeys: readonly QueryKey[], delaysMs: readonly number[]) => void;

const JobRefreshContext = createContext<JobRefreshScheduler | null>(null);

function scheduleRefreshes(
  queryKeys: readonly QueryKey[],
  delaysMs: readonly number[],
  invalidate: (queryKey: QueryKey) => void,
  trackTimeout?: (timeout: ReturnType<typeof setTimeout>) => void,
) {
  for (const delayMs of delaysMs) {
    const timeout = setTimeout(() => {
      for (const queryKey of queryKeys) {
        invalidate(queryKey);
      }
    }, delayMs);

    trackTimeout?.(timeout);
  }
}

export function JobRefreshProvider({ children }: PropsWithChildren) {
  const queryClient = useQueryClient();
  const timeoutHandlesRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const schedule = useCallback<JobRefreshScheduler>(
    (queryKeys, delaysMs) => {
      scheduleRefreshes(
        queryKeys,
        delaysMs,
        (queryKey) => {
          void queryClient.invalidateQueries({ queryKey });
        },
        (timeout) => timeoutHandlesRef.current.push(timeout),
      );
    },
    [queryClient],
  );

  useEffect(
    () => () => {
      for (const timeoutHandle of timeoutHandlesRef.current) {
        clearTimeout(timeoutHandle);
      }
      timeoutHandlesRef.current = [];
    },
    [],
  );

  return <JobRefreshContext.Provider value={schedule}>{children}</JobRefreshContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useJobRefreshScheduler(): JobRefreshScheduler {
  const providerScheduler = useContext(JobRefreshContext);
  const queryClient = useQueryClient();
  const fallbackScheduler = useCallback<JobRefreshScheduler>(
    (queryKeys, delaysMs) => {
      scheduleRefreshes(queryKeys, delaysMs, (queryKey) => {
        void queryClient.invalidateQueries({ queryKey });
      });
    },
    [queryClient],
  );

  return providerScheduler ?? fallbackScheduler;
}
