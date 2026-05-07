import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { PropsWithChildren } from "react";

import { playlistQueryKeys } from "../features/playlists/queries";
import { streamingAccountQueryKeys } from "../features/streamingAccounts/queries";
import { useDelayedInvalidate } from "./useDelayedInvalidate";

function createWrapper(queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

async function advanceTimers(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("useDelayedInvalidate", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("invalidates every query key at the default delay ticks", async () => {
    vi.useFakeTimers();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useDelayedInvalidate(), {
      wrapper: createWrapper(queryClient),
    });

    act(() => {
      result.current([playlistQueryKeys.list(), streamingAccountQueryKeys.list()]);
    });

    expect(invalidateSpy).not.toHaveBeenCalled();

    await advanceTimers(3000);

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: playlistQueryKeys.list() });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: streamingAccountQueryKeys.list() });
    expect(invalidateSpy).toHaveBeenCalledTimes(2);

    await advanceTimers(7000);

    expect(invalidateSpy).toHaveBeenCalledTimes(4);
  });

  it("clears pending invalidation timers on unmount", async () => {
    vi.useFakeTimers();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const { result, unmount } = renderHook(() => useDelayedInvalidate(), {
      wrapper: createWrapper(queryClient),
    });

    act(() => {
      result.current([playlistQueryKeys.config()]);
    });
    unmount();

    await advanceTimers(10000);

    expect(invalidateSpy).not.toHaveBeenCalled();
  });
});
