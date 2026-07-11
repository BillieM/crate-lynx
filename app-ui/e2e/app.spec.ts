import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const proposal = {
  confidence_band: "high",
  id: 44,
  local_album: "Private Archive",
  local_artist: "Frame Delay",
  local_file_path: "Frame Delay/Night Runner.mp3",
  local_title: "Night Runner File",
  local_track_id: 501,
  match_method: "tag",
  rejected_at: null,
  score: 0.92,
  status: "pending",
  streaming_album: "Late Night Drive",
  streaming_artist: "Frame Delay",
  streaming_provider_track_id: "ytm-901",
  streaming_title: "Night Runner",
  streaming_track_id: 901,
};

const generatedRun = {
  completed_at: "2026-05-24T12:00:00Z",
  created_at: "2026-05-24T11:55:00Z",
  error_detail: null,
  generation_config: {
    clustering_method: "kmeans",
    target_playlist_size: 25,
  },
  generation_number: 19,
  id: 999,
  playlist_count: 1,
  source_filter: {
    source_type: "all_local",
  },
  status: "completed",
  track_count: 24,
  updated_at: "2026-05-24T12:00:00Z",
};

const generatedPlaylist = {
  created_at: "2026-05-24T12:00:00Z",
  depth: 0,
  id: 7001,
  name: "Fast Bright",
  parent_playlist_id: null,
  position: 1,
  run_id: 999,
  summary: {
    common_tags: [{ count: 14, value: "ambient dub" }],
    representative_tracks: [{ artist: "Frame Delay", local_track_id: 501, title: "Night Runner" }],
    source_summary: { ready_track_count: 24, skipped_track_count: 0 },
    top_deltas: [{ label: "Fast" }],
  },
  track_count: 24,
};

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

async function mockApi(page: Page) {
  const requests: string[] = [];
  const unexpected: string[] = [];

  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = `${url.pathname}${url.search}`;
    requests.push(path);

    if (url.pathname === "/api/shell/summary") {
      return json(route, {
        counts: {
          library_track_total: 1,
          link_proposal_count: 1,
          relationship_suggestion_count: 0,
          soulseek_unlinked_count: 0,
          unidentified_active_count: 0,
        },
        generated_runs: [],
        playlists: [],
      });
    }

    if (url.pathname === "/api/proposals") {
      return json(route, {
        limit: 50,
        next_cursor: null,
        proposals: [proposal],
        returned_count: 1,
        total_count: 1,
      });
    }

    if (url.pathname === "/api/proposals/44") {
      return json(route, { ...proposal, state: "pending" });
    }

    if (url.pathname === "/api/library/tracks") {
      return json(route, {
        filtered_total: 1,
        limit: 100,
        next_cursor: null,
        returned_count: 1,
        stats: { linked: 1, pending: 0, total: 1, unlinked: 0 },
        tracks: [
          {
            album: "Private Archive",
            artist: "Frame Delay",
            duration_ms: 214000,
            file_path: "/library/Frame Delay/Night Runner.mp3",
            file_status: "available",
            final_link_id: 9001,
            id: 501,
            library_root_rel_path: "Frame Delay/Night Runner.mp3",
            link_status: "linked",
            match_method: "tag",
            title: "Night Runner File",
          },
        ],
      });
    }

    if (url.pathname === "/api/soulseek/queue") {
      return json(route, { filter: "all", items: [], total_count: 0 });
    }

    if (url.pathname === "/api/soulseek/status") {
      return json(route, { configured: true, detail: null, ok: true });
    }

    if (url.pathname === "/api/sonic/runs/404") {
      return json(route, { detail: "Not found" }, 404);
    }

    if (url.pathname === "/api/sonic/runs/999") {
      return json(route, { playlists: [generatedPlaylist], run: generatedRun });
    }

    if (url.pathname === "/api/sonic/generated-playlists/7001/tracks") {
      return json(route, {
        tracks: [
          {
            album: "Late Night Drive",
            artist: "Frame Delay",
            duration_ms: 214000,
            file_path: "Frame Delay/Night Runner.mp3",
            id: 1,
            library_root_rel_path: "Frame Delay/Night Runner.mp3",
            local_track_id: 501,
            position: 1,
            title: "Night Runner",
          },
        ],
      });
    }

    unexpected.push(`${route.request().method()} ${path}`);
    return json(route, { detail: `Unexpected browser fixture request: ${path}` }, 500);
  });

  return { requests, unexpected };
}

async function expectNoSeriousAccessibilityViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const seriousViolations = results.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );

  expect(seriousViolations).toEqual([]);
}

test("opens an exact proposal deep link in the production build", async ({ page }) => {
  const api = await mockApi(page);

  await page.goto("/proposals/44");

  await expect(page.getByRole("heading", { level: 1, name: "Link proposals" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Proposal queue" })).toBeVisible();
  await expect(page.getByText("Night Runner File", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /Link proposals/i })).toHaveAttribute("aria-current", "page");
  expect(api.requests).toContain("/api/proposals/44");
  expect(api.unexpected).toEqual([]);
  await expectNoSeriousAccessibilityViolations(page);
});

test("fetches an older generated run directly and distinguishes a missing run", async ({ page }) => {
  const api = await mockApi(page);

  await page.goto("/generated-runs/999");

  await expect(page.getByRole("heading", { level: 1, name: "Generated run 999" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Generation 19" })).toBeVisible();
  await expect(page.getByText("Night Runner", { exact: true })).toBeVisible();
  expect(api.requests).toContain("/api/sonic/runs/999");
  expect(api.unexpected).toEqual([]);

  await page.goto("/generated-runs/404");
  await expect(page.getByRole("heading", { level: 2, name: "Run not found" })).toBeVisible();
  await expect(page.getByText("No generated run exists with this ID. It may have been deleted.")).toBeVisible();
  expect(api.requests).toContain("/api/sonic/runs/404");
  expect(api.unexpected).toEqual([]);
});

test("supports mobile navigation as a single off-canvas flow", async ({ page }) => {
  await page.setViewportSize({ height: 844, width: 390 });
  const api = await mockApi(page);

  await page.goto("/proposals/44");
  await expect(page.getByRole("heading", { level: 1, name: "Link proposals" })).toBeVisible();

  const menuButton = page.getByRole("button", { name: "Open navigation" });
  await expect(menuButton).toHaveAttribute("aria-expanded", "false");
  await menuButton.click();

  const navigation = page.getByRole("dialog", { name: "Primary navigation" });
  await expect(navigation).toBeVisible();
  await expect(menuButton).toHaveAttribute("aria-expanded", "true");
  await expect(navigation).toBeFocused();
  await expect(navigation.getByRole("button", { name: /Link proposals/i })).toHaveAttribute("aria-current", "page");

  await navigation.getByRole("button", { name: /All tracks/i }).click();
  await expect(page).toHaveURL(/\/library$/);
  await expect(page.getByRole("heading", { level: 1, name: "All tracks" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Local library tracks" })).toBeVisible();
  await expect(page.getByRole("searchbox", { name: "Search local library" })).toBeVisible();
  await expect(page.getByRole("table")).toBeVisible();
  await expect(navigation).toBeHidden();
  await expect(menuButton).toHaveAttribute("aria-expanded", "false");

  await menuButton.click();
  const reopenedNavigation = page.getByRole("dialog", { name: "Primary navigation" });
  await reopenedNavigation.getByRole("button", { name: /Soulseek queue/i }).click();
  await expect(page).toHaveURL(/\/soulseek$/);
  await expect(page.getByRole("heading", { level: 1, name: "Soulseek Queue" })).toBeVisible();
  await page.getByRole("button", { name: "Check slskd health" }).click();
  await expect(page.getByText("slskd healthy", { exact: true })).toBeVisible();
  expect(api.unexpected).toEqual([]);
  await expectNoSeriousAccessibilityViolations(page);
});
