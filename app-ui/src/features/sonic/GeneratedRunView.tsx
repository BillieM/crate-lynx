import { createColumnHelper, type SortingState } from "@tanstack/react-table";
import { FileDown, ListTree, Music2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ActionButton } from "../../components/ActionButton";
import { DataTable } from "../../components/DataTable";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { Pill } from "../../components/Pill";
import { formatDuration } from "../../lib/formatters";
import { controlClasses, layoutClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import type { PillTone } from "../../styles/toneClasses";
import {
  type GeneratedPlaylist,
  type GeneratedPlaylistTrack,
  useGeneratedPlaylistTracksQuery,
  useSonicRunDetailQuery,
} from "./queries";

const emptyGeneratedPlaylists: GeneratedPlaylist[] = [];
const trackColumnHelper = createColumnHelper<GeneratedPlaylistTrack>();

type GeneratedPlaylistTreeRow = GeneratedPlaylist & {
  ancestorLastFlags: boolean[];
  childCount: number;
  isLastSibling: boolean;
  treeDepth: number;
};

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

function isRunInProgress(status: string) {
  return status === "pending" || status === "running";
}

function getProgressLabel(status: string) {
  return status === "pending" ? "Waiting for worker" : "Building playlists";
}

function buildPlaylistRows(playlists: GeneratedPlaylist[]): GeneratedPlaylistTreeRow[] {
  const childrenByParent = new Map<number | null, GeneratedPlaylist[]>();
  for (const playlist of playlists) {
    const parentId = playlist.parent_playlist_id ?? null;
    childrenByParent.set(parentId, [...(childrenByParent.get(parentId) ?? []), playlist]);
  }
  for (const children of childrenByParent.values()) {
    children.sort((left, right) => left.position - right.position || left.id - right.id);
  }

  const rows: GeneratedPlaylistTreeRow[] = [];
  function append(parentId: number | null, ancestorLastFlags: boolean[]) {
    const children = childrenByParent.get(parentId) ?? [];
    children.forEach((playlist, index) => {
      const isLastSibling = index === children.length - 1;
      rows.push({
        ...playlist,
        ancestorLastFlags,
        childCount: childrenByParent.get(playlist.id)?.length ?? 0,
        isLastSibling,
        treeDepth: ancestorLastFlags.length,
      });
      append(playlist.id, [...ancestorLastFlags, isLastSibling]);
    });
  }
  append(null, []);
  return rows;
}

function playlistSummaryDetails(summary: Record<string, unknown>) {
  const commonTags = Array.isArray(summary.common_tags)
    ? summary.common_tags
        .map((tag) => (isRecord(tag) && typeof tag.value === "string" ? tag.value : null))
        .filter((value): value is string => value !== null)
        .slice(0, 3)
    : [];
  const topDeltas = Array.isArray(summary.top_deltas)
    ? summary.top_deltas
        .map((delta) => (isRecord(delta) && typeof delta.label === "string" ? delta.label : null))
        .filter((value): value is string => value !== null)
        .filter((value, index, values) => values.indexOf(value) === index)
        .slice(0, 3)
    : [];
  const representativeTracks = Array.isArray(summary.representative_tracks)
    ? summary.representative_tracks
        .map((track) => {
          if (!isRecord(track)) {
            return null;
          }
          const title = typeof track.title === "string" ? track.title : null;
          const artist = typeof track.artist === "string" ? track.artist : null;
          if (!title && !artist) {
            return null;
          }
          return [title, artist].filter(Boolean).join(" - ");
        })
        .filter((value): value is string => value !== null)
        .slice(0, 3)
    : [];
  const sourceSummary = isRecord(summary.source_summary) ? summary.source_summary : null;
  const sourceReady = typeof sourceSummary?.ready_track_count === "number" ? sourceSummary.ready_track_count : null;
  const sourceSkipped = typeof sourceSummary?.skipped_track_count === "number" ? sourceSummary.skipped_track_count : null;

  if (
    commonTags.length === 0 &&
    topDeltas.length === 0 &&
    representativeTracks.length === 0 &&
    sourceReady === null &&
    sourceSkipped === null
  ) {
    return null;
  }

  return {
    commonTags,
    representativeTracks,
    sourceReady,
    sourceSkipped,
    topDeltas,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function PlaylistTreeGuides({
  ancestorLastFlags,
  isLastSibling,
  treeDepth,
}: {
  ancestorLastFlags: boolean[];
  isLastSibling: boolean;
  treeDepth: number;
}) {
  if (treeDepth === 0) {
    return <span aria-hidden="true" className="h-8 w-2 shrink-0" />;
  }

  return (
    <span aria-hidden="true" className="flex h-8 shrink-0 items-stretch">
      {ancestorLastFlags.slice(0, -1).map((isLastAncestor, index) => (
        <span className="relative w-4" key={index}>
          {isLastAncestor ? null : <span className="absolute bottom-0 left-1/2 top-0 border-l border-ctp-surface1/80" />}
        </span>
      ))}
      <span className="relative w-5">
        <span
          className={`absolute left-1/2 top-0 border-l border-ctp-surface1/80 ${
            isLastSibling ? "h-1/2" : "bottom-0"
          }`}
        />
        <span className="absolute left-1/2 top-1/2 w-3 border-t border-ctp-surface1/80" />
      </span>
    </span>
  );
}

export function GeneratedRunView({ runId }: { runId: number }) {
  const navigate = useNavigate();
  const runQuery = useSonicRunDetailQuery(runId);
  const playlists = runQuery.data?.playlists ?? emptyGeneratedPlaylists;
  const playlistRows = useMemo(() => buildPlaylistRows(playlists), [playlists]);
  const [selectedPlaylistId, setSelectedPlaylistId] = useState<number | null>(null);
  const [trackSorting, setTrackSorting] = useState<SortingState>([]);
  const tracksQuery = useGeneratedPlaylistTracksQuery(selectedPlaylistId);
  const trackColumns = useMemo(
    () => [
      trackColumnHelper.accessor("position", {
        cell: (info) => <span className="tabular-nums text-ctp-subtext0">#{info.getValue()}</span>,
        header: "Position",
        meta: {
          widthClass: "w-20",
        },
      }),
      trackColumnHelper.accessor("title", {
        cell: (info) => (
          <span className="flex max-w-[18rem] items-center gap-2 truncate font-semibold">
            <Music2 aria-hidden="true" className="h-4 w-4 shrink-0 text-ctp-subtext0" strokeWidth={1.8} />
            <span className="truncate">{info.getValue()}</span>
          </span>
        ),
        header: "Title",
        meta: {
          widthClass: "min-w-[12rem]",
        },
      }),
      trackColumnHelper.accessor("artist", {
        cell: (info) => <span className="block max-w-[14rem] truncate">{info.getValue() ?? "Artist unavailable"}</span>,
        header: "Artist",
        meta: {
          widthClass: "min-w-[10rem]",
        },
      }),
      trackColumnHelper.accessor("album", {
        cell: (info) => <span className="block max-w-[14rem] truncate">{info.getValue() ?? "Album unavailable"}</span>,
        header: "Album",
        meta: {
          hideBelow: "md",
          widthClass: "min-w-[11rem]",
        },
      }),
      trackColumnHelper.accessor("duration_ms", {
        cell: (info) => <span className="tabular-nums">{formatDuration(info.getValue())}</span>,
        header: "Duration",
        meta: {
          align: "end",
          widthClass: "w-24",
        },
      }),
      trackColumnHelper.accessor((track) => track.library_root_rel_path || track.file_path, {
        cell: (info) => <span className="block max-w-[20rem] truncate font-mono text-[11px]">{info.getValue()}</span>,
        header: "Path",
        id: "path",
        meta: {
          hideBelow: "lg",
          widthClass: "min-w-[14rem]",
        },
      }),
    ],
    [],
  );

  useEffect(() => {
    if (playlistRows.length === 0) {
      if (selectedPlaylistId !== null) {
        setSelectedPlaylistId(null);
      }
      return;
    }
    if (selectedPlaylistId !== null && playlistRows.some((playlist) => playlist.id === selectedPlaylistId)) {
      return;
    }
    setSelectedPlaylistId(playlistRows[0].id);
  }, [playlistRows, selectedPlaylistId]);

  if (runQuery.isPending) {
    return <EmptyStateCard body="Loading generated run..." className={layoutClasses.emptyStateNarrow} title="Loading run" />;
  }

  if (runQuery.isError || !runQuery.data) {
    return <EmptyStateCard body="Generated run is unavailable." className={layoutClasses.emptyStateNarrow} title="Run unavailable" tone="error" />;
  }

  const selectedPlaylist = playlists.find((playlist) => playlist.id === selectedPlaylistId) ?? null;
  const selectedSummary = selectedPlaylist ? playlistSummaryDetails(selectedPlaylist.summary) : null;
  const tracks = tracksQuery.data?.tracks ?? [];
  const run = runQuery.data.run;
  const showProgress = isRunInProgress(run.status);
  const progressLabel = getProgressLabel(run.status);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      <section className={`${surfaceClasses.compactCard} shrink-0`}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className={textClasses.sectionTitle}>Run #{run.id}</h2>
              <Pill tone={runStatusTone(run.status)}>{run.status}</Pill>
            </div>
            <p className={`mt-1 ${textClasses.bodyMuted}`}>
              {run.playlist_count.toLocaleString()} playlists · {run.track_count.toLocaleString()} tracks
            </p>
          </div>
          {selectedPlaylist ? (
            <ActionButton onClick={() => navigate(`/playlists/export?generated_playlist=${selectedPlaylist.id}`)} type="button">
              <FileDown aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
              Export
            </ActionButton>
          ) : null}
        </div>

        {showProgress ? (
          <div className="mt-3 grid gap-1.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className={textClasses.status}>{progressLabel}</p>
              <p className={textClasses.caption}>Refreshing every 2 seconds</p>
            </div>
            <div
              aria-label="Generation progress"
              aria-valuetext={progressLabel}
              className="h-1.5 overflow-hidden rounded-full bg-ctp-surface0 ring-1 ring-inset ring-ctp-surface1/70"
              role="progressbar"
            >
              <span className="sonic-progress-indicator block h-full w-1/3 rounded-full bg-ctp-mauve" />
            </div>
          </div>
        ) : null}
      </section>

      {run.error_detail ? (
        <section className={`${surfaceClasses.compactCard} border-ctp-red/40`}>
          <p className={textClasses.label}>Error</p>
          <p className={`mt-1 ${textClasses.bodyRelaxed}`}>{run.error_detail}</p>
        </section>
      ) : null}

      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(17rem,24rem)_minmax(0,1fr)]">
        <section className={`${surfaceClasses.compactCard} flex min-h-0 flex-col overflow-hidden`} aria-label="Generated playlists">
          <div className="flex shrink-0 items-center justify-between gap-3">
            <h3 className={textClasses.label}>Playlists</h3>
            <span className={`${controlClasses.countBadgeCompact} tabular-nums`}>{playlistRows.length.toLocaleString()}</span>
          </div>
          <div className="mt-3 min-h-0 flex-1 overflow-y-auto pr-1">
            {playlistRows.length > 0 ? (
              <div aria-label="Generated playlists" className="grid gap-1" role="tree">
                {playlistRows.map((playlist) => {
                  const isSelected = playlist.id === selectedPlaylistId;
                  return (
                    <button
                      aria-label={`${playlist.name}, ${playlist.track_count.toLocaleString()} tracks`}
                      aria-level={playlist.treeDepth + 1}
                      aria-selected={isSelected}
                      className={`flex min-h-9 w-full min-w-0 items-center gap-2 rounded-[8px] border px-2 py-1.5 text-left transition-colors ${
                        isSelected
                          ? "border-ctp-green/45 bg-ctp-green/10 text-ctp-text"
                          : "border-transparent text-ctp-subtext0 hover:border-ctp-surface1 hover:bg-ctp-surface0/70 hover:text-ctp-text"
                      }`}
                      key={playlist.id}
                      onClick={() => setSelectedPlaylistId(playlist.id)}
                      role="treeitem"
                      type="button"
                    >
                      <PlaylistTreeGuides
                        ancestorLastFlags={playlist.ancestorLastFlags}
                        isLastSibling={playlist.isLastSibling}
                        treeDepth={playlist.treeDepth}
                      />
                      <span
                        className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-[6px] border ${
                          playlist.childCount > 0
                            ? "border-ctp-blue/35 bg-ctp-blue/10 text-ctp-blue"
                            : "border-ctp-surface1 bg-ctp-surface0 text-ctp-subtext0"
                        }`}
                      >
                        <ListTree aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.8} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-semibold">{playlist.name}</span>
                      </span>
                      {playlist.childCount > 0 ? (
                        <span className={`${controlClasses.countBadgeCompact} shrink-0`}>{playlist.childCount}</span>
                      ) : null}
                      <span className={`${textClasses.caption} shrink-0 tabular-nums`}>
                        {playlist.track_count.toLocaleString()}
                      </span>
                    </button>
                  );
                })}
              </div>
            ) : (
              <p className={textClasses.bodyMuted}>No generated playlists stored for this run yet.</p>
            )}
          </div>
        </section>

        <section className={`${surfaceClasses.compactCard} flex min-h-0 flex-col overflow-hidden`} aria-label="Generated playlist tracks">
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className={textClasses.label}>{selectedPlaylist?.name ?? "Tracks"}</h3>
              <p className={`mt-1 ${textClasses.caption}`}>{tracks.length.toLocaleString()} visible tracks</p>
            </div>
          </div>
          {selectedSummary ? (
            <section className="mt-3 grid shrink-0 gap-2 border-t border-ctp-surface1 pt-3" aria-label="Generated playlist summary">
              {selectedSummary.commonTags.length > 0 ? (
                <p className={textClasses.caption}>Tags: {selectedSummary.commonTags.join(", ")}</p>
              ) : null}
              {selectedSummary.topDeltas.length > 0 ? (
                <p className={textClasses.caption}>Traits: {selectedSummary.topDeltas.join(", ")}</p>
              ) : null}
              {selectedSummary.representativeTracks.length > 0 ? (
                <p className={textClasses.caption}>Seeds: {selectedSummary.representativeTracks.join(", ")}</p>
              ) : null}
              {selectedSummary.sourceReady !== null || selectedSummary.sourceSkipped !== null ? (
                <p className={textClasses.caption}>
                  Source: {(selectedSummary.sourceReady ?? 0).toLocaleString()} ready,{" "}
                  {(selectedSummary.sourceSkipped ?? 0).toLocaleString()} skipped
                </p>
              ) : null}
            </section>
          ) : null}
          <div className="mt-3 min-h-0 flex-1 overflow-y-auto pr-1">
            {tracksQuery.isPending && selectedPlaylistId !== null ? (
              <p className={textClasses.bodyMuted}>Loading tracks...</p>
            ) : tracks.length > 0 ? (
              <DataTable
                columns={trackColumns}
                data={tracks}
                enableRowSelection={false}
                rowId={(track) => String(track.id)}
                sorting={trackSorting}
                stickyHeader
                onSortingChange={setTrackSorting}
              />
            ) : selectedPlaylistId !== null ? (
              <p className={textClasses.bodyMuted}>No tracks stored for this playlist.</p>
            ) : (
              <p className={textClasses.bodyMuted}>Select a generated playlist to view tracks.</p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
