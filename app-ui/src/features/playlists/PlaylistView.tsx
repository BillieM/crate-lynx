import { useEffect, useMemo, useState } from "react";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { StatusMessage } from "../../components/StatusMessage";
import { textClasses } from "../../styles/componentClasses";
import { FilterChips } from "./FilterChips";
import { filterPlaylistTracks, getPlaylistTrackFilterCounts, type PlaylistTrackFilter } from "./filterTracks";
import { PlaylistHeader } from "./PlaylistHeader";
import { PlaylistTrackActions } from "./PlaylistTrackActions";
import { PlaylistTrackRow } from "./PlaylistTrackRow";
import { usePlaylistDetailQuery, usePlaylistTracksQuery } from "./queries";
import type { PlaylistSyncViewState } from "../shell/types";

export function PlaylistView({
  isActive,
  playlistResourceId,
  syncState,
}: {
  isActive: boolean;
  playlistResourceId: number;
  syncState?: PlaylistSyncViewState;
}) {
  const [activeFilter, setActiveFilter] = useState<PlaylistTrackFilter>("all");
  const playlistDetailQuery = usePlaylistDetailQuery(isActive ? playlistResourceId : null);
  const playlistTracksQuery = usePlaylistTracksQuery(isActive ? playlistResourceId : null);
  const tracks = useMemo(() => playlistTracksQuery.data?.tracks ?? [], [playlistTracksQuery.data?.tracks]);
  const filterCounts = useMemo(() => getPlaylistTrackFilterCounts(tracks), [tracks]);
  const filteredTracks = useMemo(() => filterPlaylistTracks(tracks, activeFilter), [activeFilter, tracks]);

  useEffect(() => {
    setActiveFilter("all");
  }, [playlistResourceId]);

  if (playlistDetailQuery.isPending || playlistTracksQuery.isPending) {
    return (
      <EmptyStateCard
        body="Loading playlist overview..."
        className="text-left"
        title="Loading playlist overview"
      />
    );
  }

  if (playlistDetailQuery.isError || playlistTracksQuery.isError) {
    return (
      <EmptyStateCard
        body="Playlist overview is unavailable right now."
        className="text-left"
        title="Playlist unavailable"
        tone="error"
      />
    );
  }

  if (!playlistDetailQuery.data) {
    return null;
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-5">
      {syncState?.status === "pending" ? (
        <StatusMessage
          body="This playlist is being synced. Track counts and link status may update when the job finishes."
          status="pending"
          title="Playlist sync in progress"
        />
      ) : null}
      {syncState?.status === "error" ? (
        <StatusMessage
          body={playlistDetailQuery.data.playlist.last_sync_error ?? "The playlist sync request failed before the job could be queued."}
          status="error"
          title="Playlist sync failed"
        />
      ) : null}
      <PlaylistHeader playlist={playlistDetailQuery.data.playlist} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <FilterChips activeFilter={activeFilter} counts={filterCounts} onFilterChange={setActiveFilter} />
        <p className={`${textClasses.status} text-ctp-subtext0`}>
          Showing {filteredTracks.length} of {tracks.length} tracks
        </p>
      </div>
      <div aria-label="Playlist tracks" className="min-h-0 flex-1 overflow-y-auto pb-1 pr-1" role="region">
        {filteredTracks.length > 0 ? (
          <div className="space-y-3">
            {filteredTracks.map((track) => (
              <PlaylistTrackRow
                actionSlot={<PlaylistTrackActions playlistId={playlistResourceId} track={track} />}
                key={track.id}
                track={track}
              />
            ))}
          </div>
        ) : (
          <EmptyStateCard body="No tracks match this filter." title="No matching tracks" />
        )}
      </div>
    </section>
  );
}
