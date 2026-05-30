import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

import {
  fetchUnidentifiedTracks,
  ignoreUnidentifiedTrack,
  maintenanceQueryKeys,
  rematchLocalTrack,
  rescueLocalTrackMetadata,
  restoreUnidentifiedTrack,
  retryUnidentifiedTrack,
  type UnidentifiedTrack,
  useUnidentifiedTracksQuery,
} from "./queries";

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

describe("maintenance queries", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("builds stable query keys for maintenance reports", () => {
    expect(maintenanceQueryKeys.all).toEqual(["maintenance"]);
    expect(maintenanceQueryKeys.unidentified()).toEqual(["maintenance", "unidentified"]);
  });

  it("fetches unidentified rows from the durable maintenance route", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ tracks: [unidentifiedTrack()] }),
    } as Response);

    await expect(fetchUnidentifiedTracks()).resolves.toEqual({ tracks: [unidentifiedTrack()] });
    expect(fetchMock).toHaveBeenCalledWith("/api/maintenance/unidentified");
  });

  it("posts metadata rescue and local-track re-match to API-prefixed endpoints", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      if (url === "/api/local-tracks/4001/rescue" && init?.method === "POST") {
        return {
          ok: true,
          json: async () => ({
            beets_id: 12,
            file_path: "Artist/rescue.mp3",
            id: 4001,
            library_root_rel_path: "Artist/rescue.mp3",
          }),
        } as Response;
      }
      if (url === "/api/local-tracks/4001/rematch" && init?.method === "POST") {
        return {
          ok: true,
          json: async () => ({
            job_id: "matching-job-1",
            local_track_id: 4001,
          }),
        } as Response;
      }
      throw new Error(`Unexpected request: ${String(url)}`);
    });

    await expect(rescueLocalTrackMetadata(4001)).resolves.toMatchObject({
      id: 4001,
      library_root_rel_path: "Artist/rescue.mp3",
    });
    await expect(rematchLocalTrack(4001)).resolves.toEqual({
      job_id: "matching-job-1",
      local_track_id: 4001,
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/local-tracks/4001/rescue", { method: "POST" });
    expect(fetchMock).toHaveBeenCalledWith("/api/local-tracks/4001/rematch", { method: "POST" });
  });

  it("posts unidentified row actions to durable maintenance endpoints", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      if (url === "/api/maintenance/unidentified/4001/retry" && init?.method === "POST") {
        return {
          ok: true,
          json: async () => ({
            id: 4001,
            job_id: "ingestion-job-1",
            source_path: "ingestion/failed/unknown-import-9a4f.mp3",
          }),
        } as Response;
      }
      if (url === "/api/maintenance/unidentified/4001/ignore" && init?.method === "POST") {
        return {
          ok: true,
          json: async () => ({
            id: 4001,
            ignored_at: "2026-05-03T11:00:00Z",
            source_path: "ingestion/failed/unknown-import-9a4f.mp3",
          }),
        } as Response;
      }
      if (url === "/api/maintenance/unidentified/4001/restore" && init?.method === "POST") {
        return {
          ok: true,
          json: async () => ({
            id: 4001,
            ignored_at: null,
            source_path: "ingestion/failed/unknown-import-9a4f.mp3",
          }),
        } as Response;
      }
      throw new Error(`Unexpected request: ${String(url)}`);
    });

    await expect(retryUnidentifiedTrack(4001)).resolves.toEqual({
      id: 4001,
      job_id: "ingestion-job-1",
      source_path: "ingestion/failed/unknown-import-9a4f.mp3",
    });
    await expect(ignoreUnidentifiedTrack(4001)).resolves.toEqual({
      id: 4001,
      ignored_at: "2026-05-03T11:00:00Z",
      source_path: "ingestion/failed/unknown-import-9a4f.mp3",
    });
    await expect(restoreUnidentifiedTrack(4001)).resolves.toEqual({
      id: 4001,
      ignored_at: null,
      source_path: "ingestion/failed/unknown-import-9a4f.mp3",
    });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("throws status-coded errors when maintenance actions fail", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 409,
    } as Response);

    await expect(fetchUnidentifiedTracks()).rejects.toThrow("Request failed with status 409");
    await expect(retryUnidentifiedTrack(4001)).rejects.toThrow("Unidentified retry request failed with status 409");
    await expect(ignoreUnidentifiedTrack(4001)).rejects.toThrow("Unidentified ignore request failed with status 409");
    await expect(restoreUnidentifiedTrack(4001)).rejects.toThrow("Unidentified restore request failed with status 409");
    await expect(rematchLocalTrack(4001)).rejects.toThrow("Re-match request failed with status 409");
  });

  it("runs the unidentified hook", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ tracks: [unidentifiedTrack({ id: 4002, local_track_id: 1004 })] }),
    } as Response);

    const { result } = renderHook(() => useUnidentifiedTracksQuery(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data?.tracks[0]).toMatchObject({
      id: 4002,
      local_track_id: 1004,
    });
  });
});

function unidentifiedTrack(patch: Partial<ReturnType<typeof unidentifiedTrackShape>> = {}) {
  return {
    ...unidentifiedTrackShape(),
    ...patch,
  };
}

function unidentifiedTrackShape(): UnidentifiedTrack {
  return {
    attempt_count: 3,
    can_rematch_local_track: false,
    can_rescue_metadata: false,
    failed_at: "2026-05-02T21:44:00Z",
    failure_reason: "Beets could not identify metadata",
    filename: "unknown-import-9a4f.mp3",
    first_failed_at: "2026-05-01T20:10:00Z",
    id: 4001,
    ignored_at: null,
    local_track_id: null,
    source_mtime_ns: 1746217040000000000,
    source_path: "ingestion/failed/unknown-import-9a4f.mp3",
    source_size: 3210,
  };
}
