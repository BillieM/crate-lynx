import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Activity, AudioLines, DatabaseZap, ListChecks, Plus, RotateCcw, SlidersHorizontal } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ActionButton } from "../../components/ActionButton";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { MetricCard } from "../../components/MetricCard";
import { StatusMessage } from "../../components/StatusMessage";
import { controlClasses, layoutClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import { type StreamingPlaylist, useStreamingPlaylistsQuery } from "../playlists/queries";
import {
  backfillSonicFeatures,
  createPlaylistGenerationRun,
  sonicQueryKeys,
  type SonicTagFilter,
  useSonicFeatureSummaryQuery,
  useSonicGenerationPreviewQuery,
} from "./queries";

const emptyStreamingPlaylists: StreamingPlaylist[] = [];
const sonicBackfillLimit = 500;

type SourceType = "all_local" | "streaming_playlists";
type ClusteringMethod = "dj_hierarchical_v1" | "kmeans" | "agglomerative";
type FeatureProfile = "balanced_v1" | "energy_v1" | "texture_v1" | "harmony_v1";

const defaultTagFilter: SonicTagFilter = {
  key: "",
  match: "contains",
  scope: "item_attribute",
  value: "",
};
const previewDebounceMs = 300;

export function PlaylistGeneratorView() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const featureSummaryQuery = useSonicFeatureSummaryQuery();
  const playlistsQuery = useStreamingPlaylistsQuery();
  const playlists = playlistsQuery.data?.playlists ?? emptyStreamingPlaylists;
  const [sourceType, setSourceType] = useState<SourceType>("all_local");
  const [selectedPlaylistIds, setSelectedPlaylistIds] = useState<Set<number>>(new Set());
  const [tagFilters, setTagFilters] = useState<SonicTagFilter[]>([]);
  const [clusteringMethod, setClusteringMethod] = useState<ClusteringMethod>("dj_hierarchical_v1");
  const [featureProfile, setFeatureProfile] = useState<FeatureProfile>("balanced_v1");
  const [maxDepth, setMaxDepth] = useState(2);
  const [targetPlaylistSize, setTargetPlaylistSize] = useState(25);
  const [minPlaylistSize, setMinPlaylistSize] = useState(8);
  const [maxChildren, setMaxChildren] = useState(4);
  const [randomSeed, setRandomSeed] = useState(42);
  const selectedPlaylistIdList = useMemo(
    () => playlists.filter((playlist) => selectedPlaylistIds.has(playlist.id)).map((playlist) => playlist.id),
    [playlists, selectedPlaylistIds],
  );
  const sourceIsInvalid = sourceType === "streaming_playlists" && selectedPlaylistIdList.length === 0;
  const sanitizedTagFilters = useMemo(
    () => tagFilters.filter((filter) => filter.key.trim() && filter.value.trim()),
    [tagFilters],
  );
  const sourceFilter = useMemo(
    () => ({
      source_type: sourceType,
      streaming_playlist_ids: sourceType === "streaming_playlists" ? selectedPlaylistIdList : [],
      tag_filters: sanitizedTagFilters,
    }),
    [sanitizedTagFilters, selectedPlaylistIdList, sourceType],
  );
  const debouncedPreviewSourceFilter = useDebouncedValue(sourceFilter, previewDebounceMs);
  const generationPayload = useMemo(
    () => ({
      generation_config: {
        clustering_method: clusteringMethod,
        feature_profile: featureProfile,
        max_children: maxChildren,
        max_depth: maxDepth,
        min_playlist_size: minPlaylistSize,
        random_seed: randomSeed,
        target_playlist_size: targetPlaylistSize,
      },
      source_filter: sourceFilter,
    }),
    [
      clusteringMethod,
      featureProfile,
      maxChildren,
      maxDepth,
      minPlaylistSize,
      randomSeed,
      sourceFilter,
      targetPlaylistSize,
    ],
  );
  const previewPayload = useMemo(
    () => ({
      generation_config: {
        clustering_method: "dj_hierarchical_v1" as const,
        feature_profile: featureProfile,
        max_children: 4,
        max_depth: 2,
        min_playlist_size: 8,
        random_seed: 42,
        target_playlist_size: 25,
      },
      source_filter: debouncedPreviewSourceFilter,
    }),
    [debouncedPreviewSourceFilter, featureProfile],
  );
  const previewQuery = useSonicGenerationPreviewQuery(previewPayload, !sourceIsInvalid);
  const previewIsSettling = sourceFilter !== debouncedPreviewSourceFilter;
  const backfillMutation = useMutation({
    mutationFn: backfillSonicFeatures,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: sonicQueryKeys.featureSummary() });
    },
  });
  const createRunMutation = useMutation({
    mutationFn: createPlaylistGenerationRun,
    onSuccess: async (response) => {
      await queryClient.invalidateQueries({ queryKey: sonicQueryKeys.runs() });
      navigate(`/generated-runs/${response.run.id}`);
    },
  });

  function togglePlaylist(playlistId: number) {
    const nextSelection = new Set(selectedPlaylistIds);
    if (nextSelection.has(playlistId)) {
      nextSelection.delete(playlistId);
    } else {
      nextSelection.add(playlistId);
    }
    setSelectedPlaylistIds(nextSelection);
  }

  function updateTagFilter(index: number, patch: Partial<SonicTagFilter>) {
    setTagFilters((current) =>
      current.map((filter, filterIndex) => (filterIndex === index ? { ...filter, ...patch } : filter)),
    );
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sourceType === "streaming_playlists" && selectedPlaylistIdList.length === 0) {
      return;
    }

    if (previewIsSettling || previewQuery.isFetching || previewQuery.data?.can_generate !== true) {
      return;
    }

    createRunMutation.mutate(generationPayload);
  }

  if (featureSummaryQuery.isPending || playlistsQuery.isPending) {
    return <EmptyStateCard body="Loading sonic generation state..." className={layoutClasses.emptyStateNarrow} title="Loading" />;
  }

  if (featureSummaryQuery.isError || playlistsQuery.isError) {
    return <EmptyStateCard body="Sonic generation data is unavailable." className={layoutClasses.emptyStateNarrow} title="Unavailable" tone="error" />;
  }

  const summary = featureSummaryQuery.data;
  const hasBackfillableFeatures = summary.missing_tracks > 0 || summary.failed_tracks > 0;
  const preview = sourceIsInvalid ? undefined : previewQuery.data;
  const generateDisabled =
    createRunMutation.isPending ||
    sourceIsInvalid ||
    previewIsSettling ||
    previewQuery.isPending ||
    previewQuery.isFetching ||
    previewQuery.isError ||
    preview?.can_generate !== true;

  return (
    <form className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1" onSubmit={handleSubmit}>
      <div className="grid gap-3 md:grid-cols-4">
        <MetricCard icon={AudioLines} label="Ready" toneClass="bg-ctp-green/10 text-ctp-green ring-ctp-green/25" value={summary.ready_tracks.toLocaleString()} />
        <MetricCard icon={Activity} label="Pending" toneClass="bg-ctp-yellow/10 text-ctp-yellow ring-ctp-yellow/25" value={summary.pending_tracks.toLocaleString()} />
        <MetricCard icon={DatabaseZap} label="Missing" toneClass="bg-ctp-red/10 text-ctp-red ring-ctp-red/25" value={summary.missing_tracks.toLocaleString()} />
        <MetricCard icon={ListChecks} label="Total" toneClass="bg-ctp-blue/10 text-ctp-blue ring-ctp-blue/25" value={summary.total_tracks.toLocaleString()} />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className={textClasses.sectionTitle}>Playlist generator</h2>
          <p className={`mt-1 ${textClasses.bodyMuted}`}>{summary.ready_tracks.toLocaleString()} tracks ready</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            disabled={backfillMutation.isPending || !hasBackfillableFeatures}
            onClick={() => backfillMutation.mutate({ limit: sonicBackfillLimit })}
            type="button"
          >
            <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            {backfillMutation.isPending ? "Queueing..." : "Backfill"}
          </ActionButton>
          <ActionButton disabled={generateDisabled} type="submit">
            <Plus aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            {createRunMutation.isPending ? "Generating..." : "Generate"}
          </ActionButton>
        </div>
      </div>

      {backfillMutation.isError ? <StatusMessage body="Feature backfill could not be queued." status="error" title="Backfill failed" /> : null}
      {backfillMutation.isSuccess ? <StatusMessage body="Feature backfill job queued." status="success" title="Backfill queued" /> : null}
      {previewQuery.isError ? <StatusMessage body="Selected source readiness could not be checked." status="error" title="Preview failed" /> : null}
      {!sourceIsInvalid && preview && !preview.can_generate ? (
        <StatusMessage body="Selected source has no compatible analyzed tracks." status="pending" title="No ready tracks" />
      ) : null}
      {createRunMutation.isError ? <StatusMessage body="Generation run could not be queued." status="error" title="Generation failed" /> : null}

      <section className={`${surfaceClasses.compactCard} grid gap-3`} aria-label="Source filters">
        <div className="flex items-center gap-2 text-ctp-subtext0">
          <SlidersHorizontal aria-hidden="true" className="h-4 w-4" strokeWidth={1.8} />
          <h3 className={textClasses.label}>Source</h3>
        </div>
        <div className="grid gap-3 lg:grid-cols-[16rem_1fr]">
          <label className="grid gap-1.5" htmlFor="sonic-source-type">
            <span className={textClasses.label}>Tracks</span>
            <select
              className={`${controlClasses.controlRadius} min-h-10 border border-ctp-surface1 bg-ctp-surface0 px-3 text-ctp-text outline-none ${textClasses.input}`}
              id="sonic-source-type"
              onChange={(event) => setSourceType(event.target.value as SourceType)}
              value={sourceType}
            >
              <option value="all_local">All local tracks</option>
              <option value="streaming_playlists">Streaming playlists</option>
            </select>
          </label>

          {sourceType === "streaming_playlists" ? (
            <div className="grid gap-2">
              <span className={textClasses.label}>Playlists</span>
              <div className="grid max-h-52 gap-2 overflow-y-auto pr-1 md:grid-cols-2">
                {playlists.map((playlist) => {
                  const isSelected = selectedPlaylistIds.has(playlist.id);
                  return (
                    <button
                      className={`${surfaceClasses.rowCardCompact} text-left transition-colors ${
                        isSelected ? "border-ctp-green/45 bg-ctp-green/10" : "hover:border-ctp-surface2"
                      }`}
                      key={playlist.id}
                      onClick={() => togglePlaylist(playlist.id)}
                      type="button"
                    >
                      <span className={`block truncate ${textClasses.title}`}>{playlist.title}</span>
                      <span className={`mt-1 block ${textClasses.caption}`}>{playlist.imported_track_count.toLocaleString()} tracks</span>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}
        </div>

        <div className="grid gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className={textClasses.label}>Beets filters</span>
            <ActionButton className={controlClasses.actionButtonCompact} onClick={() => setTagFilters([...tagFilters, defaultTagFilter])} type="button">
              Add filter
            </ActionButton>
          </div>
          {tagFilters.map((filter, index) => (
            <div className="grid gap-2 md:grid-cols-[9rem_1fr_1fr_8rem_auto]" key={index}>
              <select
                className={`${controlClasses.controlRadius} min-h-10 border border-ctp-surface1 bg-ctp-surface0 px-3 text-ctp-text outline-none ${textClasses.input}`}
                onChange={(event) => updateTagFilter(index, { scope: event.target.value as SonicTagFilter["scope"] })}
                value={filter.scope}
              >
                <option value="item_attribute">Attribute</option>
                <option value="item_field">Field</option>
              </select>
              <input
                className={`${controlClasses.searchFrame} min-h-10 px-3 text-ctp-text outline-none ${textClasses.input}`}
                onChange={(event) => updateTagFilter(index, { key: event.target.value })}
                placeholder="genre"
                value={filter.key}
              />
              <input
                className={`${controlClasses.searchFrame} min-h-10 px-3 text-ctp-text outline-none ${textClasses.input}`}
                onChange={(event) => updateTagFilter(index, { value: event.target.value })}
                placeholder="ambient"
                value={filter.value}
              />
              <select
                className={`${controlClasses.controlRadius} min-h-10 border border-ctp-surface1 bg-ctp-surface0 px-3 text-ctp-text outline-none ${textClasses.input}`}
                onChange={(event) => updateTagFilter(index, { match: event.target.value as SonicTagFilter["match"] })}
                value={filter.match}
              >
                <option value="contains">Contains</option>
                <option value="equals">Equals</option>
              </select>
              <ActionButton className={controlClasses.actionButtonCompact} onClick={() => setTagFilters(tagFilters.filter((_, filterIndex) => filterIndex !== index))} type="button">
                Remove
              </ActionButton>
            </div>
          ))}
        </div>

        {preview ? (
          <div className="grid gap-2 rounded-[8px] border border-ctp-surface1 bg-ctp-surface0/45 p-3 md:grid-cols-4">
            <PreviewStat label="Source" value={preview.source_track_count} />
            <PreviewStat label="Ready" value={preview.ready_track_count} />
            <PreviewStat label="Skipped" value={preview.skipped_track_count} />
            <PreviewStat label="Profile" value={profileLabel(preview.feature_profile)} />
          </div>
        ) : null}
      </section>

      <section className={`${surfaceClasses.compactCard} grid gap-3`} aria-label="Generation parameters">
        <h3 className={textClasses.label}>Generation</h3>
        <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-7">
          <label className="grid gap-1.5">
            <span className={textClasses.label}>Profile</span>
            <select
              className={`${controlClasses.controlRadius} min-h-10 border border-ctp-surface1 bg-ctp-surface0 px-3 text-ctp-text outline-none ${textClasses.input}`}
              onChange={(event) => setFeatureProfile(event.target.value as FeatureProfile)}
              value={featureProfile}
            >
              <option value="balanced_v1">Balanced</option>
              <option value="energy_v1">Energy</option>
              <option value="texture_v1">Texture</option>
              <option value="harmony_v1">Harmony</option>
            </select>
          </label>
          <label className="grid gap-1.5">
            <span className={textClasses.label}>Method</span>
            <select
              className={`${controlClasses.controlRadius} min-h-10 border border-ctp-surface1 bg-ctp-surface0 px-3 text-ctp-text outline-none ${textClasses.input}`}
              onChange={(event) => setClusteringMethod(event.target.value as ClusteringMethod)}
              value={clusteringMethod}
            >
              <option value="dj_hierarchical_v1">DJ hierarchical</option>
              <option value="kmeans">K-means</option>
              <option value="agglomerative">Agglomerative</option>
            </select>
          </label>
          <NumericInput label="Depth" max={5} min={1} onChange={setMaxDepth} value={maxDepth} />
          <NumericInput label="Leaf size" max={500} min={2} onChange={setTargetPlaylistSize} value={targetPlaylistSize} />
          <NumericInput label="Min size" max={250} min={1} onChange={setMinPlaylistSize} value={minPlaylistSize} />
          <NumericInput label="Children" max={10} min={2} onChange={setMaxChildren} value={maxChildren} />
          <NumericInput label="Seed" max={999999} min={0} onChange={setRandomSeed} value={randomSeed} />
        </div>
      </section>
    </form>
  );
}

function PreviewStat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="min-w-0">
      <p className={textClasses.caption}>{label}</p>
      <p className="mt-0.5 truncate text-[13px] font-semibold text-ctp-text">
        {typeof value === "number" ? value.toLocaleString() : value}
      </p>
    </div>
  );
}

function profileLabel(profile: string) {
  if (profile === "energy_v1") {
    return "Energy";
  }
  if (profile === "texture_v1") {
    return "Texture";
  }
  if (profile === "harmony_v1") {
    return "Harmony";
  }
  return "Balanced";
}

function useDebouncedValue<T>(value: T, delayMs: number) {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => setDebouncedValue(value), delayMs);
    return () => window.clearTimeout(timeoutId);
  }, [delayMs, value]);

  return debouncedValue;
}

function NumericInput({
  label,
  max,
  min,
  onChange,
  value,
}: {
  label: string;
  max: number;
  min: number;
  onChange: (value: number) => void;
  value: number;
}) {
  return (
    <label className="grid gap-1.5">
      <span className={textClasses.label}>{label}</span>
      <input
        className={`${controlClasses.searchFrame} min-h-10 px-3 text-ctp-text outline-none ${textClasses.input}`}
        max={max}
        min={min}
        onChange={(event) => onChange(Number(event.target.value))}
        type="number"
        value={value}
      />
    </label>
  );
}
