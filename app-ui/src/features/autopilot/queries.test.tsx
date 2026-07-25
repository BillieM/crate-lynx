import { afterEach, describe, expect, it, vi } from "vitest";

import {
  autopilotQueryKeys,
  fetchAutopilotRun,
  fetchAutopilotRuns,
  fetchAutopilotSettings,
  runAutopilotDryRun,
  updateAutopilotSettings,
} from "./queries";

const settings = {
  created_at: "2026-07-25T19:00:00Z",
  id: 1,
  max_concurrent_downloads: 2,
  max_downloads_per_run: 12,
  max_searches_per_run: 25,
  max_storage_bytes_per_run: 8_000_000_000,
  paused: false,
  quiet_period_seconds: 900,
  retry_base_seconds: 30,
  retry_max_attempts: 3,
  retry_max_seconds: 900,
  schedule_minutes: 60,
  updated_at: "2026-07-25T20:00:00Z",
};

const run = {
  analyzed_tracks: 1,
  created_at: "2026-07-25T20:00:00Z",
  downloaded_tracks: 2,
  dry_run: true,
  failed_items: 1,
  finished_at: "2026-07-25T20:05:00Z",
  id: "run-91",
  ingested_tracks: 1,
  items: [
    {
      detail: "Runner-up margin was too small.",
      id: "item-1",
      playlist_id: 12,
      reason_code: "ambiguous_identity",
      stage: "download_gate",
      status: "needs_review",
      streaming_track_id: 55,
    },
  ],
  queued_downloads: 2,
  refreshed_exports: 0,
  refreshed_playlists: 3,
  regenerated_recipes: 0,
  review_items: 1,
  searched_tracks: 4,
  started_at: "2026-07-25T20:00:01Z",
  status: "succeeded",
  trigger: "manual",
};

describe("autopilot queries", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uses stable resource keys", () => {
    expect(autopilotQueryKeys.all).toEqual(["autopilot"]);
    expect(autopilotQueryKeys.settings()).toEqual(["autopilot", "settings"]);
    expect(autopilotQueryKeys.runs()).toEqual(["autopilot", "runs"]);
    expect(autopilotQueryKeys.run("run-91")).toEqual(["autopilot", "runs", "run-91"]);
  });

  it("loads settings, history, and item-level run detail with persistence-aligned field names", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/api/autopilot/settings") {
        return jsonResponse(settings);
      }
      if (url === "/api/autopilot/runs") {
        return jsonResponse({ runs: [run] });
      }
      if (url === "/api/autopilot/runs/run-91") {
        return jsonResponse(run);
      }
      throw new Error(`Unexpected fetch request: ${url}`);
    });

    await expect(fetchAutopilotSettings()).resolves.toMatchObject({
      max_storage_bytes_per_run: 8_000_000_000,
      max_searches_per_run: 25,
      quiet_period_seconds: 900,
      retry_max_attempts: 3,
    });
    await expect(fetchAutopilotRuns()).resolves.toMatchObject({
      runs: [{ counts: { searched_tracks: 4 } }],
    });
    await expect(fetchAutopilotRun("run-91")).resolves.toMatchObject({
      items: [{ status: "needs_review" }],
    });
  });

  it("patches bounded settings and starts only a dry-run from the UI contract", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "/api/autopilot/settings" && init?.method === "PATCH") {
        return jsonResponse({ ...settings, paused: true });
      }
      if (url === "/api/autopilot/runs" && init?.method === "POST") {
        return jsonResponse({ run });
      }
      throw new Error(`Unexpected fetch request: ${init?.method ?? "GET"} ${url}`);
    });

    const request = {
      max_concurrent_downloads: settings.max_concurrent_downloads,
      max_downloads_per_run: settings.max_downloads_per_run,
      max_searches_per_run: settings.max_searches_per_run,
      max_storage_bytes_per_run: settings.max_storage_bytes_per_run,
      paused: true,
      quiet_period_seconds: settings.quiet_period_seconds,
      retry_base_seconds: settings.retry_base_seconds,
      retry_max_attempts: settings.retry_max_attempts,
      retry_max_seconds: settings.retry_max_seconds,
      schedule_minutes: settings.schedule_minutes,
    };
    await expect(updateAutopilotSettings(request)).resolves.toMatchObject({ paused: true });
    await expect(runAutopilotDryRun()).resolves.toMatchObject({ dry_run: true, id: "run-91" });
    expect(fetchMock).toHaveBeenCalledWith("/api/autopilot/runs", {
      body: JSON.stringify({ dry_run: true }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    });
  });
});

function jsonResponse(body: unknown): Response {
  return {
    json: async () => body,
    ok: true,
    status: 200,
  } as Response;
}
