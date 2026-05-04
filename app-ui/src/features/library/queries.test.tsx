import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

import { fetchLibraryTracks, libraryQueryKeys, useLibraryTracksQuery } from "./queries";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe("library queries", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("builds stable query keys for library resources", () => {
    expect(libraryQueryKeys.all).toEqual(["library"]);
    expect(libraryQueryKeys.tracks()).toEqual(["library", "tracks"]);
  });

  it("fetches library tracks and stats from the backend endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        stats: {
          total: 3,
          linked: 1,
          pending: 1,
          unlinked: 1,
        },
        tracks: [
          {
            album: "Nocturnal",
            artist: "The Midnight",
            duration_ms: 245000,
            file_path: "Synthwave/The Midnight/Nocturnal/Night Shift.mp3",
            file_status: "available",
            id: 1001,
            library_root_rel_path: "Synthwave/The Midnight/Nocturnal/Night Shift.mp3",
            link_status: "linked",
            match_method: "isrc",
            title: "Night Shift",
          },
        ],
      }),
    } as Response);

    await expect(fetchLibraryTracks()).resolves.toEqual({
      stats: {
        total: 3,
        linked: 1,
        pending: 1,
        unlinked: 1,
      },
      tracks: [
        {
          album: "Nocturnal",
          artist: "The Midnight",
          duration_ms: 245000,
          file_path: "Synthwave/The Midnight/Nocturnal/Night Shift.mp3",
          file_status: "available",
          id: 1001,
          library_root_rel_path: "Synthwave/The Midnight/Nocturnal/Night Shift.mp3",
          link_status: "linked",
          match_method: "isrc",
          title: "Night Shift",
        },
      ],
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/library/tracks");
  });

  it("throws a status-coded error when the library request fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 503,
    } as Response);

    await expect(fetchLibraryTracks()).rejects.toThrow("Request failed with status 503");
  });

  it("runs the library tracks hook", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        stats: {
          total: 1,
          linked: 0,
          pending: 0,
          unlinked: 1,
        },
        tracks: [
          {
            album: null,
            artist: null,
            duration_ms: null,
            file_path: "unknown/import.mp3",
            file_status: "available",
            id: 1002,
            library_root_rel_path: "unknown/import.mp3",
            link_status: "unlinked",
            match_method: null,
            title: "import.mp3",
          },
        ],
      }),
    } as Response);

    const { result } = renderHook(() => useLibraryTracksQuery(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data?.stats.total).toBe(1);
    expect(result.current.data?.tracks[0]).toMatchObject({
      id: 1002,
      link_status: "unlinked",
    });
  });
});
