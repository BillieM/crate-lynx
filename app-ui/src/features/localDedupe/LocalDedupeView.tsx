import { CheckCircle2, FolderArchive, RefreshCw, ShieldX } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { ActionButton } from "../../components/ActionButton";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { FilterChipGroup, type FilterChipOption } from "../../components/FilterChipGroup";
import { Pill, type PillTone } from "../../components/Pill";
import { StatusMessage } from "../../components/StatusMessage";
import { TrackStatusDot } from "../../components/TrackStatusDot";
import { formatDuration } from "../../lib/formatters";
import { controlClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import { LocalTrackAudioPreview } from "../localTracks/LocalTrackAudioPreview";
import {
  type LocalDedupeGroup,
  type LocalDedupeSource,
  type LocalDedupeTrack,
  useDismissLocalDedupeGroupMutation,
  useLocalDedupeQueueQuery,
  useResolveLocalDedupeGroupMutation,
} from "./queries";

type QueueFilter = "all" | LocalDedupeSource;

type ActionStatus = {
  body: string;
  status: "error" | "success";
  title: string;
};

const sourceLabels = {
  fingerprint_exact: "Exact fingerprint",
  fingerprint_similar: "Similar fingerprint",
  isrc: "ISRC",
  metadata: "Metadata",
} satisfies Record<LocalDedupeSource, string>;

const sourceTones = {
  fingerprint_exact: "success",
  fingerprint_similar: "info",
  isrc: "pending",
  metadata: "neutral",
} satisfies Record<LocalDedupeSource, PillTone>;

const filterSources: Array<Omit<FilterChipOption<QueueFilter>, "count">> = [
  { label: "All", tone: "all", value: "all" },
  { label: "Exact", tone: "linked", value: "fingerprint_exact" },
  { label: "Similar", tone: "pending", value: "fingerprint_similar" },
  { label: "ISRC", tone: "pending", value: "isrc" },
  { label: "Metadata", tone: "unlinked", value: "metadata" },
];

function groupKey(group: LocalDedupeGroup) {
  return group.group_key;
}

function titleForTrack(track: LocalDedupeTrack) {
  return track.title ?? filename(track.library_root_rel_path || track.file_path);
}

function filename(path: string) {
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? path;
}

function formatScore(score: number) {
  return `${Math.round(score * 100)}%`;
}

function formatBitrate(value: number | null) {
  if (value === null) {
    return "Unknown";
  }
  return value >= 1000 ? `${Math.round(value / 1000)} kbps` : `${value} bps`;
}

function formatSampleRate(value: number | null) {
  if (value === null) {
    return "Unknown";
  }
  return `${value} Hz`;
}

function truncateMiddle(value: string | null, maxLength = 28) {
  if (!value || value.length <= maxLength) {
    return value ?? "Unavailable";
  }
  const edgeLength = Math.floor((maxLength - 1) / 2);
  return `${value.slice(0, edgeLength)}…${value.slice(-edgeLength)}`;
}

function filterForGroup(group: LocalDedupeGroup, filter: QueueFilter) {
  return filter === "all" || group.source === filter;
}

export function LocalDedupeView() {
  const queueQuery = useLocalDedupeQueueQuery();
  const resolveMutation = useResolveLocalDedupeGroupMutation();
  const dismissMutation = useDismissLocalDedupeGroupMutation();
  const [activeFilter, setActiveFilter] = useState<QueueFilter>("all");
  const [activeGroupKey, setActiveGroupKey] = useState<string | null>(null);
  const [selectedKeeperId, setSelectedKeeperId] = useState<number | null>(null);
  const [actionStatus, setActionStatus] = useState<ActionStatus | null>(null);
  const groups = useMemo(() => queueQuery.data?.groups ?? [], [queueQuery.data?.groups]);
  const visibleGroups = useMemo(
    () => groups.filter((group) => filterForGroup(group, activeFilter)),
    [activeFilter, groups],
  );
  const selectedGroup =
    visibleGroups.find((group) => groupKey(group) === activeGroupKey) ?? visibleGroups[0] ?? null;
  const selectedKeeper =
    selectedGroup?.tracks.find((track) => track.id === selectedKeeperId) ??
    selectedGroup?.tracks[0] ??
    null;
  const isBusy = resolveMutation.isPending || dismissMutation.isPending;
  const counts = useMemo(
    () =>
      filterSources.reduce<Record<QueueFilter, number>>(
        (accumulator, filter) => {
          accumulator[filter.value] =
            filter.value === "all" ? groups.length : groups.filter((group) => group.source === filter.value).length;
          return accumulator;
        },
        {
          all: 0,
          fingerprint_exact: 0,
          fingerprint_similar: 0,
          isrc: 0,
          metadata: 0,
        },
      ),
    [groups],
  );
  const filterOptions = filterSources.map((filter) => ({ ...filter, count: counts[filter.value] }));

  useEffect(() => {
    if (!selectedGroup) {
      setActiveGroupKey(null);
      setSelectedKeeperId(null);
      return;
    }

    setActiveGroupKey(groupKey(selectedGroup));
    setSelectedKeeperId((current) =>
      selectedGroup.tracks.some((track) => track.id === current) ? current : selectedGroup.tracks[0]?.id ?? null,
    );
  }, [selectedGroup]);

  function handleResolve() {
    if (!selectedGroup || !selectedKeeper || isBusy) {
      return;
    }

    setActionStatus(null);
    resolveMutation.mutate(
      {
        groupKey: selectedGroup.group_key,
        input: { keeper_local_track_id: selectedKeeper.id },
      },
      {
        onError: () => {
          setActionStatus({
            body: "The selected duplicate group could not be quarantined.",
            status: "error",
            title: "Resolve failed",
          });
        },
        onSuccess: (response) => {
          setActionStatus({
            body: `${response.decision.quarantined_local_track_ids.length} duplicate ${
              response.decision.quarantined_local_track_ids.length === 1 ? "file was" : "files were"
            } moved to quarantine.`,
            status: "success",
            title: "Duplicate group resolved",
          });
          setActiveGroupKey(null);
          setSelectedKeeperId(null);
        },
      },
    );
  }

  function handleDismiss() {
    if (!selectedGroup || isBusy) {
      return;
    }

    setActionStatus(null);
    dismissMutation.mutate(selectedGroup.group_key, {
      onError: () => {
        setActionStatus({
          body: "The selected duplicate group could not be dismissed.",
          status: "error",
          title: "Dismiss failed",
        });
      },
      onSuccess: () => {
        setActionStatus({
          body: "The duplicate group was removed from the review queue.",
          status: "success",
          title: "Group dismissed",
        });
        setActiveGroupKey(null);
        setSelectedKeeperId(null);
      },
    });
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className={textClasses.sectionTitle}>Deduplicate tracks</h2>
          <p className={`mt-1 ${textClasses.bodyMuted}`}>Review local duplicate candidates and choose the file to keep.</p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <FilterChipGroup
            activeValue={activeFilter}
            ariaLabel="Local dedupe source filters"
            density="compact"
            onValueChange={(value) => {
              setActiveFilter(value);
              setActiveGroupKey(null);
              setActionStatus(null);
            }}
            options={filterOptions}
          />
          <ActionButton
            aria-label="Refresh duplicate queue"
            className={`${controlClasses.actionButtonCompact} inline-flex items-center gap-1.5`}
            disabled={queueQuery.isFetching}
            onClick={() => {
              void queueQuery.refetch();
            }}
          >
            <RefreshCw aria-hidden="true" className={queueQuery.isFetching ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />
            Refresh
          </ActionButton>
        </div>
      </div>

      {actionStatus ? (
        <StatusMessage body={actionStatus.body} status={actionStatus.status} title={actionStatus.title} />
      ) : null}

      {queueQuery.isPending ? (
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <EmptyStateCard body="Scanning local tracks for duplicate candidates." role="status" title="Loading dedupe queue" />
        </div>
      ) : queueQuery.isError ? (
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <EmptyStateCard body="The duplicate queue could not be loaded." role="alert" title="Dedupe unavailable" tone="error" />
        </div>
      ) : visibleGroups.length === 0 ? (
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <EmptyStateCard body="No local duplicate candidates match the active filter." title="Queue empty" />
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(17rem,0.75fr)_minmax(0,1.45fr)]">
          <div className="min-h-0 overflow-y-auto pr-1" aria-label="Duplicate groups" role="region">
            <ul className="grid gap-2">
              {visibleGroups.map((group) => {
                const isSelected = selectedGroup?.group_key === group.group_key;
                const leadTrack = group.tracks[0];
                return (
                  <li key={group.group_key}>
                    <button
                      aria-pressed={isSelected}
                      className={`w-full text-left ${surfaceClasses.rowCardCompact} ${
                        isSelected ? "border-ctp-mauve/70 bg-ctp-surface0" : ""
                      }`}
                      onClick={() => {
                        setActiveGroupKey(group.group_key);
                        setSelectedKeeperId(group.tracks[0]?.id ?? null);
                        setActionStatus(null);
                      }}
                      type="button"
                    >
                      <span className="flex min-w-0 items-start justify-between gap-2">
                        <span className="min-w-0">
                          <span className={`block truncate ${textClasses.label}`}>{titleForTrack(leadTrack)}</span>
                          <span className={`block truncate ${textClasses.caption}`}>
                            {[leadTrack.artist, leadTrack.album].filter(Boolean).join(" / ") || "Local metadata unavailable"}
                          </span>
                        </span>
                        <Pill className="shrink-0" tone={sourceTones[group.source]}>
                          {formatScore(group.match_score)}
                        </Pill>
                      </span>
                      <span className="flex flex-wrap items-center gap-1.5">
                        <Pill tone={sourceTones[group.source]}>{sourceLabels[group.source]}</Pill>
                        <span className={`${textClasses.finePrint} text-ctp-subtext0 tabular-nums`}>
                          {group.tracks.length} files
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>

          <div className="min-h-0 overflow-y-auto pr-1" aria-label="Duplicate group detail" role="region">
            {selectedGroup && selectedKeeper ? (
              <article className={`${surfaceClasses.rowCard} gap-4`}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className={textClasses.eyebrow}>Selected group</p>
                    <h3 className={`mt-1 truncate ${textClasses.sectionTitle}`}>{titleForTrack(selectedKeeper)}</h3>
                    <p className={`mt-1 ${textClasses.bodyMuted}`}>
                      {sourceLabels[selectedGroup.source]} / {formatScore(selectedGroup.match_score)} / {selectedGroup.tracks.length} files
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Pill tone={sourceTones[selectedGroup.source]}>{sourceLabels[selectedGroup.source]}</Pill>
                    <Pill tone="neutral">{selectedGroup.group_key.split(":")[1]?.slice(0, 8) ?? selectedGroup.group_key}</Pill>
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  <ActionButton
                    className={`${controlClasses.actionButtonCompact} inline-flex items-center gap-1.5`}
                    disabled={isBusy}
                    tone="success"
                    onClick={handleResolve}
                  >
                    <FolderArchive aria-hidden="true" className="h-3.5 w-3.5" />
                    {resolveMutation.isPending ? "Quarantining..." : `Keep selected #${selectedKeeper.id}`}
                  </ActionButton>
                  <ActionButton
                    className={`${controlClasses.actionButtonCompact} inline-flex items-center gap-1.5`}
                    disabled={isBusy}
                    onClick={handleDismiss}
                  >
                    <ShieldX aria-hidden="true" className="h-3.5 w-3.5" />
                    {dismissMutation.isPending ? "Dismissing..." : "Dismiss"}
                  </ActionButton>
                </div>

                <section className="grid min-w-0 gap-3">
                  <div className="grid min-w-0 gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                    {selectedGroup.tracks.map((track) => (
                      <TrackInspectionCard
                        key={track.id}
                        selected={track.id === selectedKeeper.id}
                        track={track}
                        onSelectKeeper={setSelectedKeeperId}
                      />
                    ))}
                  </div>
                </section>
              </article>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}

function TrackInspectionCard({
  onSelectKeeper,
  selected,
  track,
}: {
  onSelectKeeper: (trackId: number) => void;
  selected: boolean;
  track: LocalDedupeTrack;
}) {
  return (
    <section className={`${surfaceClasses.insetPanel} min-w-0 max-w-full overflow-hidden px-3 py-3`}>
      <div className="grid min-w-0 gap-3">
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-2">
          <div className="min-w-0">
            <div className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-1.5">
              <TrackStatusDot status={track.link_status} />
              <h4 className={`truncate ${textClasses.label}`}>{titleForTrack(track)}</h4>
            </div>
            <p className={`${textClasses.caption} mt-1 truncate`}>
              {[track.artist, track.album].filter(Boolean).join(" / ") || "Local metadata unavailable"}
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
            {selected ? <Pill tone="success">Keeper</Pill> : null}
            <Pill tone="neutral">#{track.id}</Pill>
          </div>
        </div>

        <LocalTrackAudioPreview label={`Listen to ${titleForTrack(track)}`} localTrackId={track.id} />

        <dl className="grid min-w-0 gap-2 text-[11px] text-ctp-subtext0 sm:grid-cols-2">
          <Detail label="Duration" value={formatDuration(track.duration_ms)} />
          <Detail label="Format" value={track.format ?? "Unknown"} />
          <Detail label="Bitrate" value={formatBitrate(track.bitrate)} />
          <Detail label="Sample rate" value={formatSampleRate(track.samplerate)} />
          <Detail label="Bit depth" value={track.bitdepth === null ? "Unknown" : `${track.bitdepth}-bit`} />
          <Detail label="Beets ID" value={track.beets_id ?? "Unavailable"} />
          <Detail label="ISRC" value={track.isrc ?? "Unavailable"} />
          <Detail label="Final link" value={track.final_link_id ?? "None"} />
          <Detail label="Fingerprint" title={track.fingerprint ?? undefined} value={truncateMiddle(track.fingerprint)} wide />
          <Detail label="Path" title={track.library_root_rel_path} value={track.library_root_rel_path} wide />
        </dl>

        <div className="flex justify-end">
          <ActionButton
            className={`${controlClasses.actionButtonCompact} inline-flex items-center gap-1.5`}
            disabled={selected}
            tone={selected ? "success" : "neutral"}
            onClick={() => onSelectKeeper(track.id)}
          >
            <CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5" />
            {selected ? "Selected keeper" : "Select as keeper"}
          </ActionButton>
        </div>
      </div>
    </section>
  );
}

function Detail({
  label,
  title,
  value,
  wide = false,
}: {
  label: string;
  title?: string;
  value: number | string;
  wide?: boolean;
}) {
  return (
    <div className={wide ? "sm:col-span-2" : undefined}>
      <dt className="font-semibold uppercase text-ctp-overlay1">{label}</dt>
      <dd className="mt-0.5 min-w-0 [overflow-wrap:anywhere] text-ctp-text" title={title}>
        {value}
      </dd>
    </div>
  );
}
