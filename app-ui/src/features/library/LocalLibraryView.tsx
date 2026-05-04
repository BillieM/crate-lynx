import { Clock3, FileAudio, Link2, Music2, RotateCcw, SlidersHorizontal, Unlink } from "lucide-react";
import { useMemo, useState } from "react";
import { ActionButton } from "../../components/ActionButton";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { FilterChipGroup, type FilterChipOption } from "../../components/FilterChipGroup";
import { Pill, type PillTone } from "../../components/Pill";
import { StatusMessage } from "../../components/StatusMessage";
import { controlClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import { trackStatusDotClasses } from "../../styles/toneClasses";

type LibraryViewState = "ready" | "loading" | "error";
type LibraryLinkStatusFilter = "all" | "linked" | "pending" | "unlinked";
type LibraryMatchMethodFilter = "all" | "isrc" | "tag" | "acoustic" | "manual";
type LibraryFileStatusFilter = "all" | "available" | "missing" | "beets_failed";

type LibraryStat = {
  description: string;
  icon: typeof Music2;
  label: string;
  toneClass: string;
  value: number;
};

type LibraryTrack = {
  album: string | null;
  artist: string;
  durationMs: number | null;
  filePath: string;
  fileStatus: Exclude<LibraryFileStatusFilter, "all">;
  id: number;
  linkStatus: Exclude<LibraryLinkStatusFilter, "all">;
  matchMethod: Exclude<LibraryMatchMethodFilter, "all"> | null;
  title: string;
};

const libraryStats = [
  {
    description: "All imported local tracks",
    icon: Music2,
    label: "Total",
    toneClass: "bg-ctp-blue/18 text-ctp-blue ring-ctp-blue/30",
    value: 312,
  },
  {
    description: "Tracks with approved streaming links",
    icon: Link2,
    label: "Linked",
    toneClass: "bg-ctp-green/18 text-ctp-green ring-ctp-green/30",
    value: 244,
  },
  {
    description: "Tracks with suggested links awaiting review",
    icon: Clock3,
    label: "Pending",
    toneClass: "bg-ctp-yellow/18 text-ctp-yellow ring-ctp-yellow/30",
    value: 43,
  },
  {
    description: "Tracks without a usable match",
    icon: Unlink,
    label: "Unlinked",
    toneClass: "bg-ctp-red/18 text-ctp-red ring-ctp-red/30",
    value: 25,
  },
] satisfies LibraryStat[];

const linkStatusFilters = [
  {
    count: 312,
    label: "All",
    tone: "all",
    value: "all",
  },
  {
    count: 244,
    label: "Linked",
    tone: "linked",
    value: "linked",
  },
  {
    count: 43,
    label: "Pending",
    tone: "pending",
    value: "pending",
  },
  {
    count: 25,
    label: "Unlinked",
    tone: "unlinked",
    value: "unlinked",
  },
] satisfies FilterChipOption<LibraryLinkStatusFilter>[];

const matchMethodFilters = [
  { label: "All methods", value: "all" },
  { label: "ISRC", value: "isrc" },
  { label: "Tag", value: "tag" },
  { label: "Acoustic", value: "acoustic" },
  { label: "Manual", value: "manual" },
] satisfies { label: string; value: LibraryMatchMethodFilter }[];

const fileStatusFilters = [
  { label: "All files", value: "all" },
  { label: "Available locally", value: "available" },
  { label: "Missing locally", value: "missing" },
  { label: "Beets failed", value: "beets_failed" },
] satisfies { label: string; value: LibraryFileStatusFilter }[];

const libraryTracks = [
  {
    album: "Nocturnal",
    artist: "The Midnight",
    durationMs: 245000,
    filePath: "Synthwave/The Midnight/Nocturnal/Night Shift.mp3",
    fileStatus: "available",
    id: 1001,
    linkStatus: "linked",
    matchMethod: "isrc",
    title: "Night Shift",
  },
  {
    album: "Electric Youth",
    artist: "College",
    durationMs: 250000,
    filePath: "Electronic/College/Electric Youth/A Real Hero.mp3",
    fileStatus: "available",
    id: 1002,
    linkStatus: "pending",
    matchMethod: "tag",
    title: "A Real Hero",
  },
  {
    album: "Migration",
    artist: "Bonobo",
    durationMs: 360000,
    filePath: "Downtempo/Bonobo/Migration/No Reason.flac",
    fileStatus: "available",
    id: 1003,
    linkStatus: "linked",
    matchMethod: "acoustic",
    title: "No Reason",
  },
  {
    album: "Single / unknown release",
    artist: "Nils Frahm",
    durationMs: null,
    filePath: "Piano/Nils Frahm/unknown/import-9a4f.mp3",
    fileStatus: "beets_failed",
    id: 1004,
    linkStatus: "unlinked",
    matchMethod: null,
    title: "Ambre",
  },
  {
    album: "Immunity",
    artist: "Jon Hopkins",
    durationMs: 270000,
    filePath: "Electronic/Jon Hopkins/Immunity/Open Eye Signal.mp3",
    fileStatus: "missing",
    id: 1005,
    linkStatus: "pending",
    matchMethod: "manual",
    title: "Open Eye Signal",
  },
] satisfies LibraryTrack[];

const linkStatusLabels = {
  linked: "Linked",
  pending: "Pending",
  unlinked: "Unlinked",
} satisfies Record<LibraryTrack["linkStatus"], string>;

const linkStatusTones = {
  linked: "success",
  pending: "pending",
  unlinked: "danger",
} satisfies Record<LibraryTrack["linkStatus"], PillTone>;

const matchMethodLabels = {
  acoustic: "Acoustic",
  isrc: "ISRC",
  manual: "Manual",
  tag: "Tag",
} satisfies Record<Exclude<LibraryMatchMethodFilter, "all">, string>;

const fileStatusLabels = {
  available: "Available",
  beets_failed: "Beets failed",
  missing: "Missing",
} satisfies Record<LibraryTrack["fileStatus"], string>;

const fileStatusTones = {
  available: "success",
  beets_failed: "danger",
  missing: "pending",
} satisfies Record<LibraryTrack["fileStatus"], PillTone>;

function formatDuration(durationMs: number | null) {
  if (durationMs === null || durationMs < 0) {
    return "Unknown";
  }

  const totalSeconds = Math.floor(durationMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function filterLibraryTracks(
  tracks: LibraryTrack[],
  linkStatusFilter: LibraryLinkStatusFilter,
  matchMethodFilter: LibraryMatchMethodFilter,
  fileStatusFilter: LibraryFileStatusFilter,
) {
  return tracks.filter((track) => {
    const matchesLinkStatus = linkStatusFilter === "all" || track.linkStatus === linkStatusFilter;
    const matchesMatchMethod =
      matchMethodFilter === "all" || (track.matchMethod !== null && track.matchMethod === matchMethodFilter);
    const matchesFileStatus = fileStatusFilter === "all" || track.fileStatus === fileStatusFilter;

    return matchesLinkStatus && matchesMatchMethod && matchesFileStatus;
  });
}

function LibraryStatCard({ stat }: { stat: LibraryStat }) {
  const Icon = stat.icon;

  return (
    <section className={`${surfaceClasses.compactCard} min-h-28`} aria-label={`${stat.label} tracks`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className={`${textClasses.microEyebrow} text-ctp-subtext0`}>{stat.label}</p>
          <p className="mt-2 text-[28px] font-semibold leading-none tabular-nums text-ctp-text">
            {stat.value.toLocaleString()}
          </p>
        </div>
        <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-[8px] ring-1 ring-inset ${stat.toneClass}`}>
          <Icon aria-hidden="true" className="h-[18px] w-[18px]" strokeWidth={1.8} />
        </div>
      </div>
      <p className={`mt-3 ${textClasses.caption}`}>{stat.description}</p>
    </section>
  );
}

function LibrarySelectFilter<TValue extends string>({
  disabled = false,
  label,
  onValueChange,
  options,
  value,
}: {
  disabled?: boolean;
  label: string;
  onValueChange: (value: TValue) => void;
  options: { label: string; value: TValue }[];
  value: TValue;
}) {
  return (
    <label className="grid min-w-[11rem] gap-1.5">
      <span className={textClasses.microEyebrow}>{label}</span>
      <select
        className={`${controlClasses.controlRadius} min-h-9 border border-ctp-surface1 bg-ctp-surface0 px-2.5 text-[12px] font-semibold text-ctp-text outline-none transition-colors hover:border-ctp-overlay0 focus:border-ctp-blue focus:ring-2 focus:ring-ctp-blue/20`}
        disabled={disabled}
        onChange={(event) => onValueChange(event.target.value as TValue)}
        value={value}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function LibraryFilterBar({
  disabled = false,
  fileStatusFilter,
  linkStatusFilter,
  matchMethodFilter,
  onFileStatusFilterChange,
  onLinkStatusFilterChange,
  onMatchMethodFilterChange,
  onResetFilters,
}: {
  disabled?: boolean;
  fileStatusFilter: LibraryFileStatusFilter;
  linkStatusFilter: LibraryLinkStatusFilter;
  matchMethodFilter: LibraryMatchMethodFilter;
  onFileStatusFilterChange: (value: LibraryFileStatusFilter) => void;
  onLinkStatusFilterChange: (value: LibraryLinkStatusFilter) => void;
  onMatchMethodFilterChange: (value: LibraryMatchMethodFilter) => void;
  onResetFilters: () => void;
}) {
  const hasActiveFilters = linkStatusFilter !== "all" || matchMethodFilter !== "all" || fileStatusFilter !== "all";

  return (
    <section
      aria-label="Library filters"
      className={`${surfaceClasses.compactCard} flex flex-wrap items-end justify-between gap-3`}
    >
      <div className="grid min-w-0 flex-1 gap-3">
        <div className="flex items-center gap-2 text-ctp-subtext0">
          <SlidersHorizontal aria-hidden="true" className="h-4 w-4" strokeWidth={1.8} />
          <h2 className={textClasses.label}>Library filters</h2>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="grid gap-1.5">
            <span className={textClasses.microEyebrow}>Link status</span>
            <FilterChipGroup
              activeValue={linkStatusFilter}
              ariaLabel="Library link status filters"
              density="compact"
              disabled={disabled}
              onValueChange={onLinkStatusFilterChange}
              options={linkStatusFilters}
            />
          </div>
          <LibrarySelectFilter
            disabled={disabled}
            label="Match method"
            onValueChange={onMatchMethodFilterChange}
            options={matchMethodFilters}
            value={matchMethodFilter}
          />
          <LibrarySelectFilter
            disabled={disabled}
            label="File status"
            onValueChange={onFileStatusFilterChange}
            options={fileStatusFilters}
            value={fileStatusFilter}
          />
        </div>
      </div>
      <ActionButton
        aria-label="Reset library filters"
        className={`${controlClasses.actionButtonCompact} inline-flex items-center gap-1.5`}
        disabled={disabled || !hasActiveFilters}
        onClick={onResetFilters}
      >
        <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
        Reset
      </ActionButton>
    </section>
  );
}

function LibraryTrackRow({ track }: { track: LibraryTrack }) {
  const matchLabel = track.matchMethod === null ? "No match" : matchMethodLabels[track.matchMethod];
  const matchTone: PillTone = track.matchMethod === null ? "neutral" : "info";

  return (
    <article className={`${surfaceClasses.rowCardCompact} sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center`}>
      <div className="grid min-w-0 gap-1.5">
        <div className="flex min-w-0 items-center gap-3">
          <span
            aria-label={`${linkStatusLabels[track.linkStatus]} track`}
            className={`inline-flex h-2.5 w-2.5 shrink-0 rounded-full ${trackStatusDotClasses[track.linkStatus]}`}
            role="status"
          />
          <FileAudio aria-hidden="true" className="h-4 w-4 shrink-0 text-ctp-subtext0" strokeWidth={1.8} />
          <p className={`min-w-0 flex-1 truncate ${textClasses.title}`}>{track.title}</p>
          <span className={`${textClasses.metric} hidden shrink-0 sm:inline`}>{formatDuration(track.durationMs)}</span>
        </div>

        <dl
          className={`grid min-w-0 gap-x-3 gap-y-1 pl-9 text-ctp-subtext0 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] ${textClasses.bodyRelaxed}`}
        >
          <div className="flex min-w-0 items-baseline gap-1.5">
            <dt className="shrink-0 font-medium text-ctp-overlay1">Artist</dt>
            <dd className="truncate text-ctp-text">{track.artist}</dd>
          </div>
          <div className="flex min-w-0 items-baseline gap-1.5">
            <dt className="shrink-0 font-medium text-ctp-overlay1">Album</dt>
            <dd className="truncate text-ctp-text">{track.album}</dd>
          </div>
          <div className="flex min-w-0 items-baseline gap-1.5 md:justify-end">
            <dt className="shrink-0 font-medium text-ctp-overlay1">File</dt>
            <dd className="truncate font-medium text-ctp-text md:max-w-[18rem]">{track.filePath}</dd>
          </div>
          <div className="flex items-baseline gap-1.5 sm:hidden">
            <dt className="shrink-0 font-medium text-ctp-overlay1">Duration</dt>
            <dd className="font-medium tabular-nums text-ctp-text">{formatDuration(track.durationMs)}</dd>
          </div>
        </dl>
      </div>

      <div className="flex flex-wrap items-center gap-1.5 pl-9 sm:justify-end sm:pl-0">
        <Pill tone={linkStatusTones[track.linkStatus]}>{linkStatusLabels[track.linkStatus]}</Pill>
        <Pill tone={matchTone}>{matchLabel}</Pill>
        <Pill tone={fileStatusTones[track.fileStatus]}>{fileStatusLabels[track.fileStatus]}</Pill>
      </div>
    </article>
  );
}

type LocalLibraryViewProps = {
  isPending?: boolean;
  state?: LibraryViewState;
  tracks?: readonly LibraryTrack[];
};

export function LocalLibraryView({ isPending = false, state = "ready", tracks = libraryTracks }: LocalLibraryViewProps = {}) {
  const [linkStatusFilter, setLinkStatusFilter] = useState<LibraryLinkStatusFilter>("all");
  const [matchMethodFilter, setMatchMethodFilter] = useState<LibraryMatchMethodFilter>("all");
  const [fileStatusFilter, setFileStatusFilter] = useState<LibraryFileStatusFilter>("all");
  const visibleTracks = useMemo(
    () => filterLibraryTracks([...tracks], linkStatusFilter, matchMethodFilter, fileStatusFilter),
    [fileStatusFilter, linkStatusFilter, matchMethodFilter, tracks],
  );
  const controlsDisabled = state !== "ready" || isPending;

  const resetFilters = () => {
    setLinkStatusFilter("all");
    setMatchMethodFilter("all");
    setFileStatusFilter("all");
  };

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      {isPending ? (
        <StatusMessage
          body="Library rows and counts may update when the maintenance job finishes."
          status="pending"
          title="Library refresh in progress"
        />
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Library stats">
        {libraryStats.map((stat) => (
          <LibraryStatCard key={stat.label} stat={stat} />
        ))}
      </div>

      <section className="flex min-h-0 flex-1 flex-col gap-4">
        <LibraryFilterBar
          disabled={controlsDisabled}
          fileStatusFilter={fileStatusFilter}
          linkStatusFilter={linkStatusFilter}
          matchMethodFilter={matchMethodFilter}
          onFileStatusFilterChange={setFileStatusFilter}
          onLinkStatusFilterChange={setLinkStatusFilter}
          onMatchMethodFilterChange={setMatchMethodFilter}
          onResetFilters={resetFilters}
        />

        <div className="min-h-0 flex-1 overflow-y-auto pb-1 pr-1" aria-label="Local library tracks" role="region">
          {state === "loading" ? (
            <EmptyStateCard
              body="Fetching local track metadata, link states, and file availability."
              className="text-left"
              role="status"
              title="Loading library tracks"
            />
          ) : state === "error" ? (
            <EmptyStateCard
              body="Local library data could not be loaded."
              className="text-left"
              role="alert"
              title="Library unavailable"
              tone="error"
            />
          ) : visibleTracks.length > 0 ? (
            <div className="grid gap-2.5">
              <div className="flex items-center justify-between gap-3 px-1">
                <h2 className={textClasses.label}>Local library track list</h2>
                <p className={`${textClasses.caption} tabular-nums`}>
                  Showing {visibleTracks.length} of {tracks.length} rows
                </p>
              </div>
              {visibleTracks.map((track) => (
                <LibraryTrackRow key={track.id} track={track} />
              ))}
            </div>
          ) : (
            <EmptyStateCard
              body="No tracks match the selected facets."
              className="text-left"
              title="No matching library tracks"
            />
          )}
        </div>
      </section>
    </section>
  );
}
