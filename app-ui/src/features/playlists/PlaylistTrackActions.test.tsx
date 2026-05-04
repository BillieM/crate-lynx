import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { PropsWithChildren } from "react";

import { PlaylistTrackActions } from "./PlaylistTrackActions";
import type { PlaylistTrack } from "./queries";

function buildTrack(overrides: Partial<PlaylistTrack> = {}): PlaylistTrack {
  return {
    id: 81,
    provider_track_id: "ytm-track-81",
    local_track_id: 22,
    proposal_id: 54,
    final_link_id: 88,
    position: 7,
    status: "pending",
    title: "Night Shift",
    artist: "The Midnight",
    album: "Nocturnal",
    duration_ms: 245000,
    ...overrides,
  };
}

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

describe("PlaylistTrackActions", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("opens final link info for linked tracks", () => {
    render(<PlaylistTrackActions track={buildTrack({ status: "linked" })} />, {
      wrapper: createWrapper(),
    });

    fireEvent.click(screen.getByRole("button", { name: "Linked" }));

    expect(screen.getByRole("dialog")).toHaveTextContent("Final link #88");
    expect(screen.getByRole("dialog")).toHaveTextContent("local track #22");
  });

  it("calls the review navigation callback for pending tracks", () => {
    const onReviewTrack = vi.fn();
    const track = buildTrack({ status: "pending", proposal_id: 54 });

    render(<PlaylistTrackActions onReviewTrack={onReviewTrack} track={track} />, {
      wrapper: createWrapper(),
    });

    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    expect(onReviewTrack).toHaveBeenCalledWith(track);
  });

  it("renders no action for unlinked tracks", () => {
    render(<PlaylistTrackActions playlistId={12} track={buildTrack({ status: "unlinked" })} />, {
      wrapper: createWrapper(),
    });

    expect(screen.queryByRole("button", { name: "Match" })).not.toBeInTheDocument();
    expect(screen.queryByText("No local track to re-match.")).not.toBeInTheDocument();
  });

  it("renders no disabled re-match label when an unlinked row has no local track id", () => {
    render(
      <PlaylistTrackActions
        track={buildTrack({
          local_track_id: null,
          status: "unlinked",
        })}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.queryByRole("button", { name: "Match" })).not.toBeInTheDocument();
    expect(screen.queryByText("No local track to re-match.")).not.toBeInTheDocument();
  });
});
