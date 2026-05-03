import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import App, { asRgb, getProgressColor, lerp, mixColors } from "./App";

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
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
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
      }),
    } as Response);

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

  it("renders the playlist header inside the active playlist shell", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
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
      }),
    } as Response);

    renderApp();
    fireEvent.click(screen.getByRole("button", { name: /Late Night Drive/i }));

    expect(await screen.findByRole("img", { name: "Late Night Drive cover art" })).toBeInTheDocument();
    expect(screen.getByText("Playlist overview")).toBeInTheDocument();
    expect(screen.getByText("58 / 62")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/playlists/12");
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
