import { fetchShellSummary, shellQueryKeys } from "./queries";

describe("shell queries", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("builds stable shell query keys", () => {
    expect(shellQueryKeys.summary()).toEqual(["shell", "summary"]);
  });

  it("fetches the shell summary", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        counts: {
          library_track_total: 321,
          link_proposal_count: 3,
          relationship_suggestion_count: 2,
          soulseek_unlinked_count: 1,
          unidentified_active_count: 1,
        },
        generated_runs: [
          {
            completed_at: null,
            created_at: "2026-05-24T12:00:00Z",
            error_detail: null,
            generation_config: { clustering_method: "kmeans" },
            generation_number: 19,
            id: 501,
            playlist_count: 2,
            source_filter: { source_type: "all_local" },
            status: "pending",
            track_count: 58,
            updated_at: "2026-05-24T12:00:00Z",
          },
        ],
        playlists: [
          {
            account_id: 4,
            id: 12,
            imported_track_count: 62,
            last_sync_error: null,
            last_sync_error_at: null,
            metadata_synced_at: "2026-05-01T08:55:00Z",
            provider_playlist_id: "PL12",
            provider_track_count: 70,
            sync_mode: "full",
            title: "Late Night Drive",
            tracks_synced_at: "2026-05-01T09:00:00Z",
          },
        ],
      }),
    } as Response);

    await expect(fetchShellSummary()).resolves.toMatchObject({
      counts: {
        library_track_total: 321,
        link_proposal_count: 3,
      },
      generated_runs: [{ id: 501, status: "pending" }],
      playlists: [{ id: 12, title: "Late Night Drive" }],
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/shell/summary");
  });
});
