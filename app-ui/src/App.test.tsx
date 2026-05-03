import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

function renderApp(initialEntries: string[]) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("App", () => {
  afterEach(() => {
    window.fetch = fetch;
  });

  it("redirects the root route to maintenance inside the shared shell", () => {
    renderApp(["/"]);

    expect(
      screen.getByRole("heading", {
        name: /keep ingestion and recovery moving\./i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", {
        name: /sidebar/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("searchbox", {
        name: /global search/i,
      }),
    ).toBeInTheDocument();
  });

  it("keeps the shell visible on the youtube music route", () => {
    renderApp(["/youtube-music"]);

    expect(
      screen.getByRole("heading", {
        name: /review sync status and playlist linkage\./i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: /^local library$/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: /recent activity/i,
      }),
    ).toBeInTheDocument();
  });

  it("renders the local library route content within the shared main area", () => {
    renderApp(["/local-library"]);

    expect(
      screen.getByRole("heading", {
        name: /manage your source-of-truth music archive\./i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/main content area/i)).toBeInTheDocument();
  });

  it("renders progress bubbles with interpolated match states in the workspace", () => {
    renderApp(["/youtube-music"]);

    expect(
      screen.getByLabelText(/roadtrip mix: unlinked at 24% match/i),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText(/deep cuts sync: pending at 63% match/i),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText(/daily rotation: linked at 88% match/i),
    ).toBeInTheDocument();
  });

  it("shows API-backed search results in the shared topbar", async () => {
    window.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        query: "mix",
        results: [
          {
            id: 1,
            kind: "playlist",
            route_path: "/youtube-music",
            subtitle: "Playlist • 12 tracks",
            title: "Morning Mix",
          },
        ],
      }),
    } as Response);

    renderApp(["/maintenance"]);

    fireEvent.change(screen.getByRole("searchbox", { name: /global search/i }), {
      target: { value: "mix" },
    });

    await waitFor(() => {
      expect(window.fetch).toHaveBeenCalledWith("/api/search?q=mix");
    });

    expect(await screen.findByText("Morning Mix")).toBeInTheDocument();
    expect(screen.getByText("Playlist • 12 tracks")).toBeInTheDocument();
  });
});
