import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

import { playlistQueryKeys } from "../playlists/queries";
import {
  createStreamingAccount,
  fetchStreamingAccounts,
  refreshStreamingAccountAuth,
  streamingAccountQueryKeys,
  useCreateStreamingAccountMutation,
  useRefreshStreamingAccountAuthMutation,
  useStreamingAccountsQuery,
} from "./queries";

function createWrapper(queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

function failUnexpectedFetch(url: string, init?: RequestInit): never {
  throw new Error(`Unexpected fetch request: ${init?.method ?? "GET"} ${url}`);
}

const connectedAccount = {
  auth_error: null,
  auth_error_at: null,
  auth_state: "connected",
  created_at: "2026-05-01T09:00:00+00:00",
  display_name: "YouTube Music",
  id: 4,
  provider: "youtube_music",
  updated_at: "2026-05-02T09:00:00+00:00",
};

describe("streaming account queries", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("builds stable query keys disjoint from playlist keys", () => {
    expect(streamingAccountQueryKeys.all).toEqual(["streaming-accounts"]);
    expect(streamingAccountQueryKeys.list()).toEqual(["streaming-accounts", "list"]);
    expect(streamingAccountQueryKeys.list()).not.toEqual(playlistQueryKeys.list());
  });

  it("fetches streaming accounts from the accounts endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url === "/api/streaming/accounts") {
        return {
          ok: true,
          json: async () => ({
            accounts: [connectedAccount],
          }),
        } as Response;
      }

      failUnexpectedFetch(url);
    });

    await expect(fetchStreamingAccounts()).resolves.toEqual({
      accounts: [connectedAccount],
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/streaming/accounts");
  });

  it("rejects malformed streaming account payloads", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        accounts: [{ ...connectedAccount, id: "not-a-number" }],
      }),
    } as Response);

    await expect(fetchStreamingAccounts()).rejects.toThrow();
  });

  it("creates a streaming account with the expected POST payload", async () => {
    const browserHeaders = {
      cookie: "SID=fresh",
      "x-youtube-client-name": "67",
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url === "/api/streaming/accounts" && init?.method === "POST") {
        return {
          ok: true,
          json: async () => connectedAccount,
        } as Response;
      }

      failUnexpectedFetch(url, init);
    });

    await expect(
      createStreamingAccount({
        browser_headers: browserHeaders,
        display_name: "YouTube Music",
      }),
    ).resolves.toEqual(connectedAccount);
    expect(fetchMock).toHaveBeenCalledWith("/api/streaming/accounts", {
      body: JSON.stringify({
        display_name: "YouTube Music",
        browser_headers: browserHeaders,
      }),
      headers: {
        "Content-Type": "application/json",
      },
      method: "POST",
    });
  });

  it("refreshes account auth with the expected PATCH payload", async () => {
    const browserHeaders = {
      authorization: "Bearer fresh",
      cookie: "SID=fresh",
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url === "/api/streaming/accounts/4/auth" && init?.method === "PATCH") {
        return {
          ok: true,
          json: async () => connectedAccount,
        } as Response;
      }

      failUnexpectedFetch(url, init);
    });

    await expect(
      refreshStreamingAccountAuth({
        accountId: 4,
        browser_headers: browserHeaders,
      }),
    ).resolves.toEqual(connectedAccount);
    expect(fetchMock).toHaveBeenCalledWith("/api/streaming/accounts/4/auth", {
      body: JSON.stringify({ browser_headers: browserHeaders }),
      headers: {
        "Content-Type": "application/json",
      },
      method: "PATCH",
    });
  });

  it("throws when creating a streaming account fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 400,
    } as Response);

    await expect(
      createStreamingAccount({
        browser_headers: { cookie: "SID=expired" },
        display_name: "YouTube Music",
      }),
    ).rejects.toThrow("Streaming account create request failed with status 400");
  });

  it("throws when refreshing account auth fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 404,
    } as Response);

    await expect(
      refreshStreamingAccountAuth({
        accountId: 99,
        browser_headers: { cookie: "SID=expired" },
      }),
    ).rejects.toThrow("Streaming account auth refresh request failed with status 404");
  });

  it("runs the streaming accounts hook", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        accounts: [connectedAccount],
      }),
    } as Response);

    const { result } = renderHook(() => useStreamingAccountsQuery(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data?.accounts).toEqual([connectedAccount]);
  });

  it("invalidates account and playlist query keys after creating an account", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => connectedAccount,
    } as Response);

    const { result } = renderHook(() => useCreateStreamingAccountMutation(), {
      wrapper: createWrapper(queryClient),
    });

    await act(async () => {
      await result.current.mutateAsync({
        browser_headers: { cookie: "SID=fresh" },
        display_name: "YouTube Music",
      });
    });

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: streamingAccountQueryKeys.list() });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: playlistQueryKeys.list() });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: playlistQueryKeys.config() });
  });

  it("invalidates account and playlist query keys after refreshing auth", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => connectedAccount,
    } as Response);

    const { result } = renderHook(() => useRefreshStreamingAccountAuthMutation(), {
      wrapper: createWrapper(queryClient),
    });

    await act(async () => {
      await result.current.mutateAsync({
        accountId: 4,
        browser_headers: { cookie: "SID=fresh" },
      });
    });

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: streamingAccountQueryKeys.list() });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: playlistQueryKeys.list() });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: playlistQueryKeys.config() });
  });
});
