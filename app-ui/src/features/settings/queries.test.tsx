import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

import {
  createIngestFolder,
  deleteIngestFolder,
  fetchGeneralSettings,
  settingsQueryKeys,
  useCreateIngestFolderMutation,
  useDeleteIngestFolderMutation,
  useGeneralSettingsQuery,
} from "./queries";

function createWrapper(queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

function failUnexpectedFetch(url: string, init?: RequestInit): never {
  throw new Error(`Unexpected fetch request: ${init?.method ?? "GET"} ${url}`);
}

describe("settings queries", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("builds stable query keys for settings resources", () => {
    expect(settingsQueryKeys.all).toEqual(["settings"]);
    expect(settingsQueryKeys.general()).toEqual(["settings", "general"]);
    expect(settingsQueryKeys.ingestFolders()).toEqual(["settings", "ingest-folders"]);
  });

  it("fetches general settings from the settings endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        ingest_folders: [
          { id: 1, path: "/ingestion" },
          { id: 2, path: "/soulseek" },
        ],
      }),
    } as Response);

    await expect(fetchGeneralSettings()).resolves.toEqual({
      ingest_folders: [
        { id: 1, path: "/ingestion" },
        { id: 2, path: "/soulseek" },
      ],
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/settings/general");
  });

  it("creates ingest folders with the expected POST payload", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url === "/api/settings/ingest-folders" && init?.method === "POST") {
        return {
          ok: true,
          json: async () => ({ id: 3, path: "/downloads" }),
        } as Response;
      }

      failUnexpectedFetch(url, init);
    });

    await expect(createIngestFolder({ path: "/downloads" })).resolves.toEqual({ id: 3, path: "/downloads" });
    expect(fetchMock).toHaveBeenCalledWith("/api/settings/ingest-folders", {
      body: JSON.stringify({ path: "/downloads" }),
      headers: {
        "Content-Type": "application/json",
      },
      method: "POST",
    });
  });

  it("deletes ingest folders by id", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url === "/api/settings/ingest-folders/3" && init?.method === "DELETE") {
        return {
          ok: true,
        } as Response;
      }

      failUnexpectedFetch(url, init);
    });

    await expect(deleteIngestFolder(3)).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith("/api/settings/ingest-folders/3", {
      method: "DELETE",
    });
  });

  it("runs the general settings hook", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        ingest_folders: [{ id: 1, path: "/ingestion" }],
      }),
    } as Response);

    const { result } = renderHook(() => useGeneralSettingsQuery(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data?.ingest_folders).toEqual([{ id: 1, path: "/ingestion" }]);
  });

  it("invalidates general settings and ingest folder keys after creating a folder", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ id: 4, path: "/incoming" }),
    } as Response);

    const { result } = renderHook(() => useCreateIngestFolderMutation(), {
      wrapper: createWrapper(queryClient),
    });

    await act(async () => {
      await result.current.mutateAsync({ path: "/incoming" });
    });

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: settingsQueryKeys.general() });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: settingsQueryKeys.ingestFolders() });
  });

  it("invalidates general settings and ingest folder keys after deleting a folder", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
    } as Response);

    const { result } = renderHook(() => useDeleteIngestFolderMutation(), {
      wrapper: createWrapper(queryClient),
    });

    await act(async () => {
      await result.current.mutateAsync(4);
    });

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: settingsQueryKeys.general() });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: settingsQueryKeys.ingestFolders() });
  });
});
