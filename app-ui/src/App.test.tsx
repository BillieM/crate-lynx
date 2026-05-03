import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import App, { asRgb, getProgressColor, lerp, mixColors } from "./App";

const playlistDetailResponse = {
  playlist: {
    id: 12,
    account_id: 4,
    provider_playlist_id: "PL12",
    name: "Late Night Drive",
    cover_art_url: "https://cdn.example.test/late-night-drive.jpg",
    track_count: 62,
    linked_count: 58,
    pending_count: 3,
    unlinked_count: 1,
    synced_at: "2026-05-01T09:00:00Z",
  },
};

const playlistTracksResponse = {
  tracks: [
    {
      id: 101,
      provider_track_id: "ytm-101",
      position: 1,
      title: "Night Runner",
      artist: "Frame Delay",
      album: "Late Night Drive",
      duration_ms: 214000,
      status: "linked",
      local_track_id: 501,
      proposal_id: null,
      final_link_id: 9001,
    },
    {
      id: 102,
      provider_track_id: "ytm-102",
      position: 2,
      title: "Pending Signal",
      artist: "Static Gate",
      album: null,
      duration_ms: 188000,
      status: "pending",
      local_track_id: null,
      proposal_id: 44,
      final_link_id: null,
    },
    {
      id: 103,
      provider_track_id: "ytm-103",
      position: 3,
      title: "Loose Cable",
      artist: "Patch Bay",
      album: "Maintenance Window",
      duration_ms: null,
      status: "unlinked",
      local_track_id: 503,
      proposal_id: null,
      final_link_id: null,
    },
  ],
};

function mockPlaylistFetch() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);

    if (url === "/api/playlists/12/m3u") {
      return {
        ok: true,
        blob: async () => new Blob(["#EXTM3U\n/library/night-runner.flac\n"], { type: "audio/x-mpegurl" }),
        headers: new Headers({
          "Content-Disposition": 'attachment; filename="Late Night Drive.m3u"',
        }),
      } as Response;
    }

    if (url === "/api/streaming/accounts/4/sync" && init?.method === "POST") {
      return {
        ok: true,
        json: async () => ({ account_id: 4, job_id: "sync-job-4" }),
      } as Response;
    }

    if (url === "/api/playlists/12/tracks") {
      return {
        ok: true,
        json: async () => playlistTracksResponse,
      } as Response;
    }

    return {
      ok: true,
      json: async () => playlistDetailResponse,
    } as Response;
  });
}

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

describe("App", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("renders the fixed-height shell container, sidebar scaffold, and topbar", () => {
    const { container } = renderApp();

    expect(container.firstChild).toHaveClass("flex", "flex-1", "flex-row", "overflow-hidden", "bg-ctp-base", "text-ctp-text");

    const shell = container.querySelector(".bg-ctp-base");

    expect(shell).toHaveClass("flex", "flex-1", "flex-row", "overflow-hidden", "bg-ctp-base", "text-ctp-text");

    const sidebar = screen.getByRole("complementary");

    expect(sidebar).toHaveClass("w-[220px]", "bg-ctp-mantle", "border-r", "border-ctp-surface0");
    expect(screen.getByText("MUSEBRIDGE")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Search tracks, artists, playlists")).toBeInTheDocument();
    expect(screen.getByText("Maintenance")).toBeInTheDocument();
    expect(screen.getByText("YouTube Music")).toBeInTheDocument();
    expect(screen.getByText("Local Library")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Link proposals/i })).toBeInTheDocument();
    expect(screen.getByText("58")).toBeInTheDocument();
    expect(screen.getByText("62")).toBeInTheDocument();
    expect(screen.getByText("312")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Link proposals" })).toBeInTheDocument();
    expect(screen.getByText("Needs approval")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync" })).not.toBeInTheDocument();

    for (const viewId of [
      "proposals",
      "unidentified",
      "missing",
      "playlist",
      "playlist2",
      "playlist3",
      "playlist4",
      "playlist5",
      "library",
    ]) {
      expect(document.getElementById(viewId)).toBeInTheDocument();
    }
  });

  it("updates the topbar config when a playlist nav item is selected", () => {
    mockPlaylistFetch();

    renderApp();

    expect(document.getElementById("proposals")).toHaveAttribute("data-view-active", "true");
    expect(document.getElementById("playlist")).toHaveAttribute("data-view-active", "false");

    fireEvent.click(screen.getByRole("button", { name: /Late Night Drive/i }));

    expect(screen.getByRole("heading", { name: "Late Night Drive" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Late Night Drive/i })).toBeInTheDocument();
    expect(screen.getAllByText("YouTube Music")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Sync" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export M3U" })).toBeInTheDocument();
    expect(document.getElementById("proposals")).toHaveAttribute("data-view-active", "false");
    expect(document.getElementById("playlist")).toHaveAttribute("data-view-active", "true");
  });

  it("renders the playlist view inside the active playlist shell", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp();
    fireEvent.click(screen.getByRole("button", { name: /Late Night Drive/i }));

    expect(await screen.findByRole("img", { name: "Late Night Drive cover art" })).toBeInTheDocument();
    expect(screen.getByText("Playlist overview")).toBeInTheDocument();
    expect(screen.getByText("58 / 62")).toBeInTheDocument();
    expect(screen.getByText("Night Runner")).toBeInTheDocument();
    expect(screen.getByText("Pending Signal")).toBeInTheDocument();
    expect(screen.getByText("Loose Cable")).toBeInTheDocument();
    expect(screen.getByText("Showing 3 of 3 tracks")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/playlists/12");
    expect(fetchMock).toHaveBeenCalledWith("/api/playlists/12/tracks");
  });

  it("queues a YouTube Music sync from the active playlist topbar", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp();
    fireEvent.click(screen.getByRole("button", { name: /Late Night Drive/i }));

    const syncButton = await screen.findByRole("button", { name: "Sync" });
    await waitFor(() => {
      expect(syncButton).toBeEnabled();
    });

    fireEvent.click(syncButton);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/accounts/4/sync", { method: "POST" });
    });
    expect(await screen.findByText("Sync queued.")).toBeInTheDocument();
  });

  it("downloads an M3U export from the active playlist topbar", async () => {
    const fetchMock = mockPlaylistFetch();
    const createObjectUrlMock = vi.fn(() => "blob:playlist-export");
    const revokeObjectUrlMock = vi.fn();
    const clickMock = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    Object.defineProperty(window.URL, "createObjectURL", {
      configurable: true,
      value: createObjectUrlMock,
    });
    Object.defineProperty(window.URL, "revokeObjectURL", {
      configurable: true,
      value: revokeObjectUrlMock,
    });

    renderApp();
    fireEvent.click(screen.getByRole("button", { name: /Late Night Drive/i }));

    const exportButton = await screen.findByRole("button", { name: "Export M3U" });
    fireEvent.click(exportButton);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/playlists/12/m3u");
    });

    expect(await screen.findByText("M3U ready.")).toBeInTheDocument();
    expect(createObjectUrlMock).toHaveBeenCalledWith(expect.any(Blob));
    expect(clickMock).toHaveBeenCalled();
    expect(revokeObjectUrlMock).toHaveBeenCalledWith("blob:playlist-export");
  });

  it("filters playlist tracks by status", async () => {
    mockPlaylistFetch();

    renderApp();
    fireEvent.click(screen.getByRole("button", { name: /Late Night Drive/i }));

    expect(await screen.findByText("Night Runner")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Pending/i }));

    expect(screen.getByText("Pending Signal")).toBeInTheDocument();
    expect(screen.queryByText("Night Runner")).not.toBeInTheDocument();
    expect(screen.queryByText("Loose Cable")).not.toBeInTheDocument();
    expect(screen.getByText("Showing 1 of 3 tracks")).toBeInTheDocument();
  });

  it("debounces sidebar search requests and renders compact results", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        query: "mix",
        results: [
          {
            id: 1,
            kind: "playlist",
            title: "Morning Mix",
            subtitle: "Playlist • 12 tracks",
            route_path: "/youtube-music",
          },
          {
            id: 2,
            kind: "local_track",
            title: "Mixdown.mp3",
            subtitle: "Local file • Artist/Mixdown.mp3",
            route_path: "/local-library",
          },
        ],
      }),
    } as Response);

    renderApp();

    fireEvent.change(screen.getByPlaceholderText("Search tracks, artists, playlists"), {
      target: { value: "mix" },
    });

    expect(fetchMock).not.toHaveBeenCalled();

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/search?q=mix");
    });

    expect(await screen.findByText("Morning Mix")).toBeInTheDocument();
    expect(screen.getByText("Mixdown.mp3")).toBeInTheDocument();
    expect(screen.getByText("Playlist")).toBeInTheDocument();
    expect(screen.getByText("Local")).toBeInTheDocument();
  });

  it("interpolates scalar values with rounding", () => {
    expect(lerp(10, 20, 0.45)).toBe(15);
  });

  it("mixes RGB colors channel by channel", () => {
    expect(
      mixColors(
        { red: 10, green: 20, blue: 30 },
        { red: 40, green: 80, blue: 120 },
        0.5,
      ),
    ).toEqual({ red: 25, green: 50, blue: 75 });
  });

  it("maps progress percentages onto the Catppuccin gradient", () => {
    expect(getProgressColor(-10)).toEqual({ red: 108, green: 112, blue: 134 });
    expect(getProgressColor(50)).toEqual({ red: 249, green: 226, blue: 175 });
    expect(getProgressColor(100)).toEqual({ red: 166, green: 227, blue: 161 });
  });

  it("formats rgba strings with optional alpha", () => {
    expect(asRgb({ red: 1, green: 2, blue: 3 })).toBe("rgba(1, 2, 3, 1)");
    expect(asRgb({ red: 1, green: 2, blue: 3 }, 0.4)).toBe("rgba(1, 2, 3, 0.4)");
  });
});
