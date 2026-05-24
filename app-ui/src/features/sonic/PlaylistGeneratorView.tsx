import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Activity, AudioLines, DatabaseZap, ListChecks, Plus, RotateCcw, SlidersHorizontal } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
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
} from "./queries";

const emptyStreamingPlaylists: StreamingPlaylist[] = [];

type SourceType = "all_local" | "streaming_playlists";
type ClusteringMethod = "kmeans" | "agglomerative";

const defaultTagFilter: SonicTagFilter = {
  key: "",
  match: "contains",
  scope: "item_attribute",
  value: "",
};

export function PlaylistGeneratorView() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const featureSummaryQuery = useSonicFeatureSummaryQuery();
  const playlistsQuery = useStreamingPlaylistsQuery();
  const playlists = playlistsQuery.data?.playlists ?? emptyStreamingPlaylists;
  const [sourceType, setSourceType] = useState<SourceType>("all_local");
  const [selectedPlaylistIds, setSelectedPlaylistIds] = useState<Set<number>>(new Set());
  const [tagFilters, setTagFilters] = useState<SonicTagFilter[]>([]);
  const [clusteringMethod, setClusteringMethod] = useState<ClusteringMethod>("kmeans");
  const [maxDepth, setMaxDepth] = useState(2);
  const [targetPlaylistSize, setTargetPlaylistSize] = useState(25);
  const [minPlaylistSize, setMinPlaylistSize] = useState(8);
  const [maxChildren, setMaxChildren] = useState(4);
  const [randomSeed, setRandomSeed] = useState(42);
  const selectedPlaylistIdList = useMemo(
    () => playlists.filter((playlist) => selectedPlaylistIds.has(playlist.id)).map((playlist) => playlist.id),
    [playlists, selectedPlaylistIds],
  );
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

    createRunMutation.mutate({
      generation_config: {
        clustering_method: clusteringMethod,
        feature_profile: "balanced_v1",
        max_children: maxChildren,
        max_depth: maxDepth,
        min_playlist_size: minPlaylistSize,
        random_seed: randomSeed,
        target_playlist_size: targetPlaylistSize,
      },
      source_filter: {
        source_type: sourceType,
        streaming_playlist_ids: sourceType === "streaming_playlists" ? selectedPlaylistIdList : [],
        tag_filters: tagFilters.filter((filter) => filter.key.trim() && filter.value.trim()),
      },
    });
  }

  if (featureSummaryQuery.isPending || playlistsQuery.isPending) {
    return <EmptyStateCard body="Loading sonic generation state..." className={layoutClasses.emptyStateNarrow} title="Loading" />;
  }

  if (featureSummaryQuery.isError || playlistsQuery.isError) {
    return <EmptyStateCard body="Sonic generation data is unavailable." className={layoutClasses.emptyStateNarrow} title="Unavailable" tone="error" />;
  }

  const summary = featureSummaryQuery.data;
  const sourceIsInvalid = sourceType === "streaming_playlists" && selectedPlaylistIdList.length === 0;

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
            disabled={backfillMutation.isPending || summary.missing_tracks === 0}
            onClick={() => backfillMutation.mutate({ limit: 100 })}
            type="button"
          >
            <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            {backfillMutation.isPending ? "Queueing..." : "Backfill"}
          </ActionButton>
          <ActionButton disabled={createRunMutation.isPending || sourceIsInvalid || summary.ready_tracks === 0} type="submit">
            <Plus aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            {createRunMutation.isPending ? "Generating..." : "Generate"}
          </ActionButton>
        </div>
      </div>

      {backfillMutation.isError ? <StatusMessage body="Feature backfill could not be queued." status="error" title="Backfill failed" /> : null}
      {backfillMutation.isSuccess ? <StatusMessage body="Feature backfill job queued." status="success" title="Backfill queued" /> : null}
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
      </section>

      <section className={`${surfaceClasses.compactCard} grid gap-3`} aria-label="Generation parameters">
        <h3 className={textClasses.label}>Generation</h3>
        <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
          <label className="grid gap-1.5">
            <span className={textClasses.label}>Method</span>
            <select
              className={`${controlClasses.controlRadius} min-h-10 border border-ctp-surface1 bg-ctp-surface0 px-3 text-ctp-text outline-none ${textClasses.input}`}
              onChange={(event) => setClusteringMethod(event.target.value as ClusteringMethod)}
              value={clusteringMethod}
            >
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
