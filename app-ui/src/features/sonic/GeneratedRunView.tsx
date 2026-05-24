import { FileDown, Music2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ActionButton } from "../../components/ActionButton";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { Pill } from "../../components/Pill";
import { formatDuration } from "../../lib/formatters";
import { controlClasses, layoutClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import type { PillTone } from "../../styles/toneClasses";
import {
  type GeneratedPlaylist,
  useGeneratedPlaylistTracksQuery,
  useSonicRunDetailQuery,
} from "./queries";

const emptyGeneratedPlaylists: GeneratedPlaylist[] = [];

function runStatusTone(status: string): PillTone {
  if (status === "completed") {
    return "success";
  }
  if (status === "failed") {
    return "danger";
  }
  if (status === "running") {
    return "pending";
  }
  return "neutral";
}

function buildPlaylistRows(playlists: GeneratedPlaylist[]) {
  const childrenByParent = new Map<number | null, GeneratedPlaylist[]>();
  for (const playlist of playlists) {
    const parentId = playlist.parent_playlist_id ?? null;
    childrenByParent.set(parentId, [...(childrenByParent.get(parentId) ?? []), playlist]);
  }
  for (const children of childrenByParent.values()) {
    children.sort((left, right) => left.position - right.position || left.id - right.id);
  }

  const rows: Array<GeneratedPlaylist & { indent: number }> = [];
  function append(parentId: number | null, indent: number) {
    for (const playlist of childrenByParent.get(parentId) ?? []) {
      rows.push({ ...playlist, indent });
      append(playlist.id, indent + 1);
    }
  }
  append(null, 0);
  return rows;
}

export function GeneratedRunView() {
  const navigate = useNavigate();
  const params = useParams();
  const runId = params.runId ?? null;
  const numericRunId = runId && /^\d+$/.test(runId) ? Number(runId) : null;
  const runQuery = useSonicRunDetailQuery(numericRunId);
  const playlists = runQuery.data?.playlists ?? emptyGeneratedPlaylists;
  const playlistRows = useMemo(() => buildPlaylistRows(playlists), [playlists]);
  const [selectedPlaylistId, setSelectedPlaylistId] = useState<number | null>(null);
  const tracksQuery = useGeneratedPlaylistTracksQuery(selectedPlaylistId);

  useEffect(() => {
    if (selectedPlaylistId !== null || playlistRows.length === 0) {
      return;
    }
    setSelectedPlaylistId(playlistRows[0].id);
  }, [playlistRows, selectedPlaylistId]);

  if (numericRunId === null) {
    return <EmptyStateCard body="Generated run route is invalid." className={layoutClasses.emptyStateNarrow} title="Invalid run" tone="error" />;
  }

  if (runQuery.isPending) {
    return <EmptyStateCard body="Loading generated run..." className={layoutClasses.emptyStateNarrow} title="Loading run" />;
  }

  if (runQuery.isError || !runQuery.data) {
    return <EmptyStateCard body="Generated run is unavailable." className={layoutClasses.emptyStateNarrow} title="Run unavailable" tone="error" />;
  }

  const selectedPlaylist = playlists.find((playlist) => playlist.id === selectedPlaylistId) ?? null;
  const tracks = tracksQuery.data?.tracks ?? [];

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <section className={`${surfaceClasses.compactCard} flex flex-wrap items-start justify-between gap-3`}>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className={textClasses.sectionTitle}>Run #{runQuery.data.run.id}</h2>
            <Pill tone={runStatusTone(runQuery.data.run.status)}>{runQuery.data.run.status}</Pill>
          </div>
          <p className={`mt-1 ${textClasses.bodyMuted}`}>
            {runQuery.data.run.playlist_count.toLocaleString()} playlists · {runQuery.data.run.track_count.toLocaleString()} tracks
          </p>
        </div>
        {selectedPlaylist ? (
          <ActionButton onClick={() => navigate(`/playlists/export?generated_playlist=${selectedPlaylist.id}`)} type="button">
            <FileDown aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            Export
          </ActionButton>
        ) : null}
      </section>

      {runQuery.data.run.error_detail ? (
        <section className={`${surfaceClasses.compactCard} border-ctp-red/40`}>
          <p className={textClasses.label}>Error</p>
          <p className={`mt-1 ${textClasses.bodyRelaxed}`}>{runQuery.data.run.error_detail}</p>
        </section>
      ) : null}

      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(18rem,24rem)_1fr]">
        <section className={`${surfaceClasses.compactCard} min-h-0 overflow-hidden`} aria-label="Generated playlists">
          <h3 className={textClasses.label}>Playlists</h3>
          <div className="mt-3 grid max-h-full gap-2 overflow-y-auto pr-1">
            {playlistRows.map((playlist) => {
              const isSelected = playlist.id === selectedPlaylistId;
              return (
                <button
                  className={`${surfaceClasses.rowCardCompact} text-left transition-colors ${
                    isSelected ? "border-ctp-green/45 bg-ctp-green/10" : "hover:border-ctp-surface2"
                  }`}
                  key={playlist.id}
                  onClick={() => setSelectedPlaylistId(playlist.id)}
                  style={{ paddingLeft: `${12 + playlist.indent * 16}px` }}
                  type="button"
                >
                  <span className={`block truncate ${textClasses.title}`}>{playlist.name}</span>
                  <span className={`mt-1 block ${textClasses.caption}`}>{playlist.track_count.toLocaleString()} tracks</span>
                </button>
              );
            })}
          </div>
        </section>

        <section className={`${surfaceClasses.compactCard} min-h-0 overflow-hidden`} aria-label="Generated playlist tracks">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className={textClasses.label}>{selectedPlaylist?.name ?? "Tracks"}</h3>
              <p className={`mt-1 ${textClasses.caption}`}>{tracks.length.toLocaleString()} visible tracks</p>
            </div>
          </div>
          <div className="mt-3 min-h-0 overflow-y-auto pr-1">
            <div className="grid gap-2">
              {tracks.map((track) => (
                <div className={`${surfaceClasses.rowCardCompact} flex min-w-0 items-center gap-3`} key={track.id}>
                  <span className={`${controlClasses.iconFrame} h-8 w-8 shrink-0`}>
                    <Music2 aria-hidden="true" className="h-4 w-4" strokeWidth={1.8} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={`block truncate ${textClasses.title}`}>{track.title}</span>
                    <span className={`mt-1 block truncate ${textClasses.caption}`}>
                      {track.artist ?? "Artist unavailable"} · {track.album ?? "Album unavailable"}
                    </span>
                  </span>
                  <span className={`shrink-0 tabular-nums ${textClasses.caption}`}>{formatDuration(track.duration_ms)}</span>
                </div>
              ))}
              {tracksQuery.isPending && selectedPlaylistId !== null ? (
                <p className={textClasses.bodyMuted}>Loading tracks...</p>
              ) : null}
              {!tracksQuery.isPending && selectedPlaylistId !== null && tracks.length === 0 ? (
                <p className={textClasses.bodyMuted}>No tracks stored for this playlist.</p>
              ) : null}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
