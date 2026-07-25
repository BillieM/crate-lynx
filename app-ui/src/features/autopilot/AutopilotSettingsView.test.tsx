import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AutopilotSettingsView } from "./AutopilotSettingsView";

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
  analyzed_tracks: 2,
  created_at: "2026-07-25T20:00:00Z",
  downloaded_tracks: 2,
  dry_run: true,
  failed_items: 1,
  finished_at: "2026-07-25T20:05:00Z",
  id: "run-91",
  ingested_tracks: 2,
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
    {
      detail: "The imported file was unreadable.",
      id: "item-2",
      playlist_id: 12,
      reason_code: "corrupt_audio",
      stage: "post_import_verification",
      status: "failed",
      streaming_track_id: 56,
    },
  ],
  queued_downloads: 2,
  refreshed_exports: 1,
  refreshed_playlists: 3,
  regenerated_recipes: 1,
  review_items: 1,
  searched_tracks: 4,
  started_at: "2026-07-25T20:00:01Z",
  status: "succeeded",
  trigger: "manual",
};

function renderView() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <AutopilotSettingsView />
    </QueryClientProvider>,
  );
}

describe("AutopilotSettingsView", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows bounded controls, compact counts, failures, and review work, then saves and dry-runs safely", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "/api/autopilot/settings" && init?.method === undefined) {
        return jsonResponse(settings);
      }
      if (url === "/api/autopilot/settings" && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body)) as Partial<typeof settings>;
        return jsonResponse({ ...settings, ...body, updated_at: "2026-07-25T20:10:00Z" });
      }
      if (url === "/api/autopilot/runs" && init?.method === undefined) {
        return jsonResponse({ runs: [run] });
      }
      if (url === "/api/autopilot/runs/run-91" && init?.method === undefined) {
        return jsonResponse(run);
      }
      if (url === "/api/autopilot/runs" && init?.method === "POST") {
        return jsonResponse({ run });
      }
      throw new Error(`Unexpected fetch request: ${init?.method ?? "GET"} ${url}`);
    });

    renderView();

    expect(await screen.findByRole("heading", { name: "Autopilot" })).toBeInTheDocument();
    expect(screen.getByLabelText("Run every (minutes)")).toHaveValue(60);
    expect(screen.getByLabelText("Quiet period (minutes)")).toHaveValue(15);
    expect(screen.getByLabelText("Missing-track searches per run")).toHaveValue(25);
    expect(screen.getByLabelText("Storage per run (GB)")).toHaveValue(8);
    expect(
      screen.getByText(/Set to 0 to refresh and reconcile without acquisition searches/),
    ).toBeInTheDocument();
    expect((await screen.findByText("Needs review (1)")).closest("section")).toHaveTextContent(
      "Runner-up margin was too small.",
    );
    expect(screen.getByText("Failures (1)").closest("section")).toHaveTextContent(
      "The imported file was unreadable.",
    );
    expect(screen.getByText(/Searched 4 · queued 2 · ingested 2/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: /Global pause \/ kill switch/ }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/autopilot/settings", {
        body: JSON.stringify({ paused: true }),
        headers: { "Content-Type": "application/json" },
        method: "PATCH",
      });
    });
    fireEvent.change(screen.getByLabelText("Missing-track searches per run"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("Downloads per run"), { target: { value: "6" } });
    fireEvent.click(screen.getByRole("button", { name: "Save automation settings" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/autopilot/settings", {
        body: JSON.stringify({
          max_concurrent_downloads: 2,
          max_downloads_per_run: 6,
          max_searches_per_run: 0,
          max_storage_bytes_per_run: 8_000_000_000,
          paused: true,
          quiet_period_seconds: 900,
          retry_base_seconds: 30,
          retry_max_attempts: 3,
          retry_max_seconds: 900,
          schedule_minutes: 60,
        }),
        headers: { "Content-Type": "application/json" },
        method: "PATCH",
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "Run safe dry-run" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/autopilot/runs", {
        body: JSON.stringify({ dry_run: true }),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      });
    });
    expect(await screen.findByText("Dry-run queued")).toBeInTheDocument();
  });
});

function jsonResponse(body: unknown): Response {
  return {
    json: async () => body,
    ok: true,
    status: 200,
  } as Response;
}
