import { type QueryKey, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef } from "react";

const defaultDelaysMs = [3000, 10000] as const;

export function useDelayedInvalidate(): (
  queryKeys: readonly QueryKey[],
  delaysMs?: readonly number[],
) => void {
  const queryClient = useQueryClient();
  const timeoutHandlesRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(
    () => () => {
      for (const timeoutHandle of timeoutHandlesRef.current) {
        clearTimeout(timeoutHandle);
      }

      timeoutHandlesRef.current = [];
    },
    [],
  );

  return useCallback(
    (queryKeys: readonly QueryKey[], delaysMs: readonly number[] = defaultDelaysMs) => {
      for (const delayMs of delaysMs) {
        const timeoutHandle = setTimeout(() => {
          timeoutHandlesRef.current = timeoutHandlesRef.current.filter((candidate) => candidate !== timeoutHandle);

          for (const queryKey of queryKeys) {
            void queryClient.invalidateQueries({ queryKey });
          }
        }, delayMs);

        timeoutHandlesRef.current.push(timeoutHandle);
      }
    },
    [queryClient],
  );
}
