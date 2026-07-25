import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createColumnHelper, type RowSelectionState, type SortingState } from "@tanstack/react-table";
import {
  Activity,
  AudioLines,
  ChevronDown,
  ChevronRight,
  CircleX,
  DatabaseZap,
  ListChecks,
  Minus,
  Plus,
  RotateCcw,
  Save,
  SlidersHorizontal,
  Trash2,
  Undo2,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ActionButton } from "../../components/ActionButton";
import { DataTable } from "../../components/DataTable";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { IconButton } from "../../components/IconButton";
import { MetricCard } from "../../components/MetricCard";
import { Pill, type PillTone } from "../../components/Pill";
import { StatusMessage } from "../../components/StatusMessage";
import { formatPlaylistTimestamp } from "../../lib/formatters";
import { setSessionDraftCodec, useSessionDraftState } from "../../lib/useSessionDraftState";
import { controlClasses, layoutClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import {
  type M3uExportProfile,
  type StreamingPlaylist,
  useM3uExportProfilesQuery,
  useStreamingPlaylistsQuery,
} from "../playlists/queries";
import { shellSummaryInvalidationKeys } from "../shell/queries";
import {
  backfillSonicFeatures,
  createPlaylistGenerationRun,
  sonicQueryKeys,
  type PlaylistGenerationProjection,
  type PlaylistGenerationRecipe,
  type PlaylistGenerationRun,
  type PlaylistGenerationConfig,
  type SavePlaylistGenerationRecipeRequest,
  type SequenceIntent,
  type SonicTagFilter,
  type SonicPreviewPlaylist,
  type SonicPreviewTrack,
  useCreatePlaylistGenerationRecipeMutation,
  useDeletePlaylistGenerationRecipeMutation,
  usePlaylistGenerationRecipesQuery,
  useRegeneratePlaylistGenerationRecipeMutation,
  useSonicFeatureSummaryQuery,
  useSonicGenerationPreviewQuery,
  useDeleteSelectedPlaylistGenerationRunsMutation,
  useSonicRunsQuery,
  useUpdatePlaylistGenerationRecipeMutation,
} from "./queries";

const emptyStreamingPlaylists: StreamingPlaylist[] = [];
const emptyGenerationRuns: PlaylistGenerationRun[] = [];
const emptyRecipes: PlaylistGenerationRecipe[] = [];
const emptyExportProfiles: M3uExportProfile[] = [];
const runColumnHelper = createColumnHelper<PlaylistGenerationRun>();
const sonicBackfillLimit = 500;
const numberSetSessionDraftCodec = setSessionDraftCodec<number>();
const generatorDraftKey = (field: string) => `crate-lynx:playlist-generator:v2:${field}`;

type SourceType = "all_local" | "streaming_playlists";
type ClusteringMethod = PlaylistGenerationConfig["clustering_method"];
type DiversityMode = PlaylistGenerationConfig["diversity_mode"];
type FeatureProfile = PlaylistGenerationConfig["feature_profile"];
type NamingStrategy = PlaylistGenerationConfig["naming_strategy"];
type OrderingStrategy = PlaylistGenerationConfig["ordering_strategy"];
type OutputScope = PlaylistGenerationConfig["output_scope"];
type PresetKey = PlaylistGenerationConfig["preset_key"];
type SemanticMode = PlaylistGenerationConfig["semantic_mode"];
type TempoMode = PlaylistGenerationConfig["tempo_mode"];
type NumericConfigKey = "maxChildren" | "maxDepth" | "minPlaylistSize" | "randomSeed" | "targetPlaylistSize";
type NumericDrafts = Record<NumericConfigKey, string>;
type NumericValues = Record<NumericConfigKey, number>;

type RecipeMutationStatus = {
  body: string;
  status: "error" | "success";
  title: string;
};

type RunBulkStatus = {
  body: string;
  status: "error" | "success";
  title: string;
};

type GenerationPreset = {
  clusteringMethod: ClusteringMethod;
  description: string;
  diversityMode: DiversityMode;
  featureProfile: FeatureProfile;
  key: PresetKey;
  label: string;
  namingStrategy: NamingStrategy;
  orderingStrategy: OrderingStrategy;
  outputScope: OutputScope;
  tempoMode: TempoMode;
};

const defaultTagFilter: SonicTagFilter = {
  key: "",
  match: "contains",
  scope: "item_attribute",
  value: "",
};
const previewDebounceMs = 300;
const sequenceIntentOptions = [
  {
    description: "Prioritise small tempo, energy, and harmonic transitions where the evidence is reliable.",
    label: "Smooth mix",
    value: "smooth_mix",
  },
  {
    description: "Build steadily from lower-energy selections toward a stronger finish.",
    label: "Rising energy",
    value: "rising_energy",
  },
  {
    description: "Shape a patient opening, controlled build, and a clear peak.",
    label: "Warm-up to peak",
    value: "warm_up_to_peak",
  },
  {
    description: "Balance contrast and repetition for varied everyday listening.",
    label: "Varied listening",
    value: "varied_listening",
  },
] satisfies Array<{ description: string; label: string; value: SequenceIntent }>;

const fallbackNumericValues: NumericValues = {
  maxChildren: 4,
  maxDepth: 2,
  minPlaylistSize: 8,
  randomSeed: 42,
  targetPlaylistSize: 25,
};

const numericFieldSpecs: Record<
  NumericConfigKey,
  {
    impact: string;
    label: string;
    max: number;
    min: number;
    step: number;
  }
> = {
  maxChildren: {
    impact: "Higher branches wider at each level; lower keeps fewer sibling crates.",
    label: "Children",
    max: 10,
    min: 2,
    step: 1,
  },
  maxDepth: {
    impact: "Higher creates nested crates; lower keeps the run flatter.",
    label: "Depth",
    max: 5,
    min: 1,
    step: 1,
  },
  minPlaylistSize: {
    impact: "Higher prevents tiny splits; lower allows niche crates.",
    label: "Min size",
    max: 250,
    min: 1,
    step: 1,
  },
  randomSeed: {
    impact: "Changes deterministic tie-breaks without changing the source.",
    label: "Seed",
    max: 999999,
    min: 0,
    step: 1,
  },
  targetPlaylistSize: {
    impact: "Higher makes fewer, broader playlists; lower makes more focused playlists.",
    label: "Leaf size",
    max: 500,
    min: 2,
    step: 1,
  },
};

const generationPresets: GenerationPreset[] = [
  {
    clusteringMethod: "dj_hierarchical_v1",
    description: "Balanced mix-ready crates, with leaf playlists as the default output.",
    diversityMode: "balanced_v1",
    featureProfile: "balanced_v1",
    key: "dj_crate_tree_v1",
    label: "Mix-ready crates",
    namingStrategy: "dj_utility_v1",
    orderingStrategy: "profile_nearest_neighbor_rolling_v2",
    outputScope: "leaf_only_v1",
    tempoMode: "mixable_v1",
  },
  {
    clusteringMethod: "dj_hierarchical_v1",
    description: "Functional warm-up, build, and peak slots.",
    diversityMode: "strict_v1",
    featureProfile: "energy_v1",
    key: "set_builder_v1",
    label: "Set builder",
    namingStrategy: "functional_slot_v1",
    orderingStrategy: "profile_nearest_neighbor_rolling_v2",
    outputScope: "leaf_only_v1",
    tempoMode: "mixable_v1",
  },
  {
    clusteringMethod: "kmeans",
    description: "Seeded variety crates for rediscovery.",
    diversityMode: "strict_v1",
    featureProfile: "balanced_v1",
    key: "discovery_sampler_v1",
    label: "Discovery sampler",
    namingStrategy: "crate_label_v1",
    orderingStrategy: "seeded_shuffle_v1",
    outputScope: "leaf_only_v1",
    tempoMode: "mixable_v1",
  },
  {
    clusteringMethod: "agglomerative",
    description: "Acoustic texture collections with conservative, evidence-backed names.",
    diversityMode: "balanced_v1",
    featureProfile: "texture_v1",
    key: "metadata_collections_v1",
    label: "Texture collections",
    namingStrategy: "metadata_tagline_v1",
    orderingStrategy: "center_out_v1",
    outputScope: "leaf_only_v1",
    tempoMode: "raw_v1",
  },
  {
    clusteringMethod: "dj_hierarchical_v1",
    description: "Small focused leaf crates for export.",
    diversityMode: "balanced_v1",
    featureProfile: "balanced_v1",
    key: "micro_crates_v1",
    label: "Micro crates",
    namingStrategy: "crate_label_v1",
    orderingStrategy: "profile_nearest_neighbor_rolling_v2",
    outputScope: "leaf_only_v1",
    tempoMode: "mixable_v1",
  },
];

function runStatusTone(status: PlaylistGenerationRun["status"]): PillTone {
  if (status === "completed") {
    return "success";
  }
  if (status === "failed") {
    return "danger";
  }
  if (status === "running" || status === "pending") {
    return "pending";
  }
  return "neutral";
}

function isRunDeletable(run: PlaylistGenerationRun) {
  return run.status === "completed" || run.status === "failed";
}

export function PlaylistGeneratorView() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const featureSummaryQuery = useSonicFeatureSummaryQuery();
  const exportProfilesQuery = useM3uExportProfilesQuery();
  const playlistsQuery = useStreamingPlaylistsQuery();
  const recipesQuery = usePlaylistGenerationRecipesQuery();
  const runsQuery = useSonicRunsQuery();
  const playlists = playlistsQuery.data?.playlists ?? emptyStreamingPlaylists;
  const exportProfiles = exportProfilesQuery.data?.profiles ?? emptyExportProfiles;
  const recipes = recipesQuery.data?.recipes ?? emptyRecipes;
  const generationRuns = runsQuery.data?.runs ?? emptyGenerationRuns;
  const [sourceType, setSourceType] = useSessionDraftState<SourceType>(generatorDraftKey("source-type"), "all_local");
  const [selectedPlaylistIds, setSelectedPlaylistIds] = useSessionDraftState<Set<number>>(
    generatorDraftKey("playlist-ids"),
    () => new Set(),
    numberSetSessionDraftCodec,
  );
  const [tagFilters, setTagFilters] = useSessionDraftState<SonicTagFilter[]>(generatorDraftKey("tag-filters"), []);
  const [runRowSelection, setRunRowSelection] = useState<RowSelectionState>({});
  const [runSorting, setRunSorting] = useState<SortingState>([]);
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);
  const [bulkDeleteStatus, setBulkDeleteStatus] = useState<RunBulkStatus | null>(null);
  const [recipeName, setRecipeName] = useState("");
  const [editingRecipeId, setEditingRecipeId] = useState<number | null>(null);
  const [recipeEnabled, setRecipeEnabled] = useState(true);
  const [recipeRegenerateOnChange, setRecipeRegenerateOnChange] = useState(true);
  const [recipeAutoExport, setRecipeAutoExport] = useState(false);
  const [recipeExportProfileId, setRecipeExportProfileId] = useState<number | null>(null);
  const [recipeMutationStatus, setRecipeMutationStatus] = useState<RecipeMutationStatus | null>(null);
  const [sequenceIntent, setSequenceIntent] = useSessionDraftState<SequenceIntent>(
    generatorDraftKey("sequence-intent"),
    "smooth_mix",
  );
  const [presetKey, setPresetKey] = useSessionDraftState<PresetKey>(generatorDraftKey("preset"), "dj_crate_tree_v1");
  const [clusteringMethod, setClusteringMethod] = useSessionDraftState<ClusteringMethod>(
    generatorDraftKey("clustering-method"),
    "dj_hierarchical_v1",
  );
  const [featureProfile, setFeatureProfile] = useSessionDraftState<FeatureProfile>(generatorDraftKey("feature-profile"), "balanced_v1");
  const [namingStrategy, setNamingStrategy] = useSessionDraftState<NamingStrategy>(generatorDraftKey("naming-strategy"), "dj_utility_v1");
  const [orderingStrategy, setOrderingStrategy] = useSessionDraftState<OrderingStrategy>(
    generatorDraftKey("ordering-strategy"),
    "profile_nearest_neighbor_rolling_v2",
  );
  const [diversityMode, setDiversityMode] = useSessionDraftState<DiversityMode>(generatorDraftKey("diversity-mode"), "balanced_v1");
  const [tempoMode, setTempoMode] = useSessionDraftState<TempoMode>(generatorDraftKey("tempo-mode"), "mixable_v1");
  const [semanticMode, setSemanticMode] = useSessionDraftState<SemanticMode>(
    generatorDraftKey("semantic-mode"),
    "off",
  );
  const [semanticWeight, setSemanticWeight] = useSessionDraftState(
    generatorDraftKey("semantic-weight"),
    0.15,
  );
  const [outputScope, setOutputScope] = useSessionDraftState<OutputScope>(
    generatorDraftKey("output-scope"),
    "leaf_only_v1",
  );
  const [numericDrafts, setNumericDrafts] = useSessionDraftState<NumericDrafts>(
    generatorDraftKey("numeric-values"),
    () => numericValuesToDrafts(fallbackNumericValues),
  );
  const [numericDefaultsAreAdaptive, setNumericDefaultsAreAdaptive] = useSessionDraftState(
    generatorDraftKey("adaptive-numeric-values"),
    true,
  );
  const [advancedOpen, setAdvancedOpen] = useSessionDraftState(generatorDraftKey("advanced-open"), false);
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
  const previewReadyTrackCount = featureSummaryQuery.data?.ready_tracks ?? fallbackNumericValues.targetPlaylistSize;
  const activePreset = generationPresets.find((preset) => preset.key === presetKey) ?? generationPresets[0];
  const adaptiveNumericValues = useMemo(
    () => adaptiveNumericDefaults(previewReadyTrackCount, presetKey),
    [presetKey, previewReadyTrackCount],
  );
  const numericValues = useMemo(
    () => normalizeNumericDrafts(numericDrafts, adaptiveNumericValues),
    [adaptiveNumericValues, numericDrafts],
  );
  const generationConfig = useMemo(
    () => ({
      clustering_method: clusteringMethod,
      diversity_mode: diversityMode,
      feature_profile: featureProfile,
      max_children: numericValues.maxChildren,
      max_depth: numericValues.maxDepth,
      min_playlist_size: numericValues.minPlaylistSize,
      naming_strategy: namingStrategy,
      ordering_strategy: orderingStrategy,
      output_scope: outputScope,
      preset_key: presetKey,
      random_seed: numericValues.randomSeed,
      semantic_mode: semanticMode,
      semantic_weight: semanticWeight,
      sequencing_intent: sequenceIntent,
      target_playlist_size: numericValues.targetPlaylistSize,
      tempo_mode: tempoMode,
    }),
    [
      clusteringMethod,
      diversityMode,
      featureProfile,
      namingStrategy,
      numericValues,
      orderingStrategy,
      outputScope,
      presetKey,
      semanticMode,
      semanticWeight,
      sequenceIntent,
      tempoMode,
    ],
  );
  const debouncedPreviewSourceFilter = useDebouncedValue(sourceFilter, previewDebounceMs);
  const generationPayload = useMemo(
    () => ({
      generation_config: generationConfig,
      source_filter: sourceFilter,
    }),
    [generationConfig, sourceFilter],
  );
  const previewPayload = useMemo(
    () => ({
      generation_config: generationConfig,
      source_filter: debouncedPreviewSourceFilter,
    }),
    [debouncedPreviewSourceFilter, generationConfig],
  );
  const previewQuery = useSonicGenerationPreviewQuery(previewPayload, !sourceIsInvalid);
  const previewIsSettling = sourceFilter !== debouncedPreviewSourceFilter;
  useEffect(() => {
    if (recipeExportProfileId !== null || exportProfiles.length === 0) {
      return;
    }
    const defaultProfile = exportProfiles.find((profile) => profile.is_default) ?? exportProfiles[0];
    setRecipeExportProfileId(defaultProfile.id);
  }, [exportProfiles, recipeExportProfileId]);
  useEffect(() => {
    if (!numericDefaultsAreAdaptive) {
      return;
    }
    const readyCount = previewQuery.data?.ready_track_count ?? featureSummaryQuery.data?.ready_tracks ?? fallbackNumericValues.targetPlaylistSize;
    setNumericDrafts(numericValuesToDrafts(adaptiveNumericDefaults(readyCount, presetKey)));
  }, [
    featureSummaryQuery.data?.ready_tracks,
    numericDefaultsAreAdaptive,
    presetKey,
    previewQuery.data?.ready_track_count,
    setNumericDrafts,
  ]);
  const backfillMutation = useMutation({
    mutationFn: backfillSonicFeatures,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: sonicQueryKeys.featureSummary() });
    },
  });
  const createRunMutation = useMutation({
    mutationFn: createPlaylistGenerationRun,
    onSuccess: async (response) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: sonicQueryKeys.runs() }),
        ...shellSummaryInvalidationKeys().map((queryKey) => queryClient.invalidateQueries({ queryKey })),
      ]);
      navigate(`/generated-runs/${response.run.id}`);
    },
  });
  const deleteSelectedRunsMutation = useDeleteSelectedPlaylistGenerationRunsMutation();
  const createRecipeMutation = useCreatePlaylistGenerationRecipeMutation();
  const updateRecipeMutation = useUpdatePlaylistGenerationRecipeMutation();
  const deleteRecipeMutation = useDeletePlaylistGenerationRecipeMutation();
  const regenerateRecipeMutation = useRegeneratePlaylistGenerationRecipeMutation();
  const selectedRunIds = useMemo(
    () =>
      generationRuns
        .filter((run) => runRowSelection[String(run.id)] && isRunDeletable(run))
        .map((run) => run.id),
    [generationRuns, runRowSelection],
  );
  const latestCompletedRunId = generationRuns.find((run) => run.status === "completed")?.id ?? null;
  const runColumns = useMemo(
    () => [
      runColumnHelper.accessor("generation_number", {
        cell: (info) => <span className="font-semibold tabular-nums">Generation {info.getValue()}</span>,
        header: "Run",
        meta: {
          widthClass: "min-w-[9rem]",
        },
      }),
      runColumnHelper.accessor("status", {
        cell: (info) => <Pill tone={runStatusTone(info.getValue())}>{info.getValue()}</Pill>,
        header: "Status",
        meta: {
          widthClass: "w-28",
        },
      }),
      runColumnHelper.accessor("playlist_count", {
        cell: (info) => <span className="tabular-nums">{info.getValue().toLocaleString()}</span>,
        header: "Playlists",
        meta: {
          align: "end",
          widthClass: "w-24",
        },
      }),
      runColumnHelper.accessor("track_count", {
        cell: (info) => <span className="tabular-nums">{info.getValue().toLocaleString()}</span>,
        header: "Tracks",
        meta: {
          align: "end",
          widthClass: "w-24",
        },
      }),
      runColumnHelper.accessor("created_at", {
        cell: (info) => <span className="whitespace-nowrap text-ctp-subtext0">{formatPlaylistTimestamp(info.getValue())}</span>,
        header: "Created",
        meta: {
          hideBelow: "md",
          widthClass: "min-w-[12rem]",
        },
      }),
    ],
    [],
  );

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

  function handlePresetChange(nextPresetKey: PresetKey) {
    const nextPreset = generationPresets.find((preset) => preset.key === nextPresetKey) ?? generationPresets[0];
    setPresetKey(nextPreset.key);
    setClusteringMethod(nextPreset.clusteringMethod);
    setFeatureProfile(nextPreset.featureProfile);
    setNamingStrategy(nextPreset.namingStrategy);
    setOrderingStrategy(nextPreset.orderingStrategy);
    setDiversityMode(nextPreset.diversityMode);
    setTempoMode(nextPreset.tempoMode);
    setOutputScope(nextPreset.outputScope);
    setNumericDefaultsAreAdaptive(true);
    setNumericDrafts(
      numericValuesToDrafts(
        adaptiveNumericDefaults(
          previewQuery.data?.ready_track_count ?? featureSummaryQuery.data?.ready_tracks ?? fallbackNumericValues.targetPlaylistSize,
          nextPreset.key,
        ),
      ),
    );
  }

  function updateNumericDraft(key: NumericConfigKey, value: string) {
    setNumericDefaultsAreAdaptive(false);
    setNumericDrafts((current) => ({ ...current, [key]: value }));
  }

  function normalizeNumericDraft(key: NumericConfigKey) {
    setNumericDrafts((current) => ({
      ...current,
      [key]: String(normalizeNumericValue(key, current[key], adaptiveNumericValues[key])),
    }));
  }

  function stepNumericDraft(key: NumericConfigKey, direction: -1 | 1) {
    const spec = numericFieldSpecs[key];
    setNumericDefaultsAreAdaptive(false);
    setNumericDrafts((current) => {
      const currentValue = normalizeNumericValue(key, current[key], adaptiveNumericValues[key]);
      return {
        ...current,
        [key]: String(clampNumber(currentValue + spec.step * direction, spec.min, spec.max)),
      };
    });
  }

  function resetNumericDraft(key: NumericConfigKey) {
    setNumericDrafts((current) => ({ ...current, [key]: String(adaptiveNumericValues[key]) }));
  }

  function resetAdaptiveDefaults() {
    setNumericDefaultsAreAdaptive(true);
    setNumericDrafts(
      numericValuesToDrafts(
        adaptiveNumericDefaults(
          previewQuery.data?.ready_track_count ?? featureSummaryQuery.data?.ready_tracks ?? fallbackNumericValues.targetPlaylistSize,
          presetKey,
        ),
      ),
    );
  }

  function buildRecipePayload(): SavePlaylistGenerationRecipeRequest {
    return {
      enabled: recipeEnabled,
      export_config: recipeAutoExport
        ? {
            enabled: true,
            formats: ["m3u8"],
            path_format: "absolute",
            profile_id: recipeExportProfileId,
            scope: "leaf_only",
          }
        : null,
      generation_config: generationConfig,
      name: recipeName.trim(),
      regenerate_on_change: recipeRegenerateOnChange,
      source_filter: sourceFilter,
    };
  }

  function resetRecipeEditor() {
    setEditingRecipeId(null);
    setRecipeName("");
    setRecipeEnabled(true);
    setRecipeRegenerateOnChange(true);
    setRecipeAutoExport(false);
  }

  function handleSaveRecipe() {
    if (!recipeName.trim() || sourceIsInvalid) {
      return;
    }

    setRecipeMutationStatus(null);
    const payload = buildRecipePayload();
    const callbacks = {
      onError: () => {
        setRecipeMutationStatus({
          body: "The saved recipe could not be written.",
          status: "error" as const,
          title: "Recipe save failed",
        });
      },
      onSuccess: (savedRecipe: PlaylistGenerationRecipe) => {
        resetRecipeEditor();
        setRecipeMutationStatus({
          body: `${savedRecipe.name} is ready to regenerate against the latest eligible library.`,
          status: "success" as const,
          title: editingRecipeId === null ? "Recipe saved" : "Recipe updated",
        });
      },
    };

    if (editingRecipeId === null) {
      createRecipeMutation.mutate(payload, callbacks);
      return;
    }

    updateRecipeMutation.mutate({ payload, recipeId: editingRecipeId }, callbacks);
  }

  function loadRecipe(recipe: PlaylistGenerationRecipe) {
    const config = recipe.generation_config;
    const recipeSource = recipe.source_filter;
    const sourceTypeValue = recipeSource.source_type;
    const playlistIds = recipeSource.streaming_playlist_ids;
    const filters = recipeSource.tag_filters;

    setEditingRecipeId(recipe.id);
    setRecipeName(recipe.name);
    setRecipeEnabled(recipe.enabled);
    setRecipeRegenerateOnChange(recipe.regenerate_on_change);
    setRecipeAutoExport(Boolean(recipe.export_config?.enabled));
    setRecipeExportProfileId(
      typeof recipe.export_config?.profile_id === "number" ? recipe.export_config.profile_id : null,
    );
    setSourceType(sourceTypeValue === "streaming_playlists" ? "streaming_playlists" : "all_local");
    setSelectedPlaylistIds(
      new Set(Array.isArray(playlistIds) ? playlistIds.filter((id): id is number => typeof id === "number") : []),
    );
    setTagFilters(
      Array.isArray(filters)
        ? filters.filter(
            (filter): filter is SonicTagFilter =>
              typeof filter === "object" &&
              filter !== null &&
              typeof (filter as Record<string, unknown>).key === "string" &&
              typeof (filter as Record<string, unknown>).value === "string",
          )
        : [],
    );
    setSequenceIntent(readStringOption(config.sequencing_intent, sequenceIntentOptions, "smooth_mix"));
    setPresetKey(readStringValue(config.preset_key, "dj_crate_tree_v1") as PresetKey);
    setClusteringMethod(readStringValue(config.clustering_method, "dj_hierarchical_v1") as ClusteringMethod);
    setFeatureProfile(readStringValue(config.feature_profile, "balanced_v1") as FeatureProfile);
    setNamingStrategy(readStringValue(config.naming_strategy, "dj_utility_v1") as NamingStrategy);
    setOrderingStrategy(
      readStringValue(config.ordering_strategy, "profile_nearest_neighbor_rolling_v2") as OrderingStrategy,
    );
    setDiversityMode(readStringValue(config.diversity_mode, "balanced_v1") as DiversityMode);
    setSemanticMode(readStringValue(config.semantic_mode, "off") as SemanticMode);
    setSemanticWeight(readNumberValue(config.semantic_weight, 0.15));
    setTempoMode(readStringValue(config.tempo_mode, "mixable_v1") as TempoMode);
    setOutputScope(readStringValue(config.output_scope, "leaf_only_v1") as OutputScope);
    setNumericDefaultsAreAdaptive(false);
    setNumericDrafts(
      numericValuesToDrafts({
        maxChildren: readNumberValue(config.max_children, fallbackNumericValues.maxChildren),
        maxDepth: readNumberValue(config.max_depth, fallbackNumericValues.maxDepth),
        minPlaylistSize: readNumberValue(config.min_playlist_size, fallbackNumericValues.minPlaylistSize),
        randomSeed: readNumberValue(config.random_seed, fallbackNumericValues.randomSeed),
        targetPlaylistSize: readNumberValue(
          config.target_playlist_size,
          fallbackNumericValues.targetPlaylistSize,
        ),
      }),
    );
    setRecipeMutationStatus(null);
  }

  function handleRegenerateRecipe(recipe: PlaylistGenerationRecipe) {
    setRecipeMutationStatus(null);
    regenerateRecipeMutation.mutate(recipe.id, {
      onError: () => {
        setRecipeMutationStatus({
          body: `${recipe.name} could not be queued.`,
          status: "error",
          title: "Regeneration failed",
        });
      },
      onSuccess: (response) => {
        navigate(`/generated-runs/${response.run_id}`);
      },
    });
  }

  function handleDeleteRecipe(recipe: PlaylistGenerationRecipe) {
    setRecipeMutationStatus(null);
    deleteRecipeMutation.mutate(recipe.id, {
      onError: () => {
        setRecipeMutationStatus({
          body: `${recipe.name} could not be deleted.`,
          status: "error",
          title: "Recipe delete failed",
        });
      },
      onSuccess: () => {
        if (editingRecipeId === recipe.id) {
          resetRecipeEditor();
        }
        setRecipeMutationStatus({
          body: `${recipe.name} was deleted. Existing immutable runs were left untouched.`,
          status: "success",
          title: "Recipe deleted",
        });
      },
    });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sourceType === "streaming_playlists" && selectedPlaylistIdList.length === 0) {
      return;
    }

    if (previewIsSettling || previewQuery.isFetching || previewQuery.data?.can_generate !== true) {
      return;
    }

    setNumericDrafts(numericValuesToDrafts(numericValues));
    createRunMutation.mutate(generationPayload);
  }

  function selectGenerationRuns(predicate: (run: PlaylistGenerationRun) => boolean) {
    setConfirmBulkDelete(false);
    setBulkDeleteStatus(null);
    setRunRowSelection(
      Object.fromEntries(
        generationRuns.filter((run) => isRunDeletable(run) && predicate(run)).map((run) => [String(run.id), true]),
      ),
    );
  }

  function handleDeleteSelectedRuns() {
    if (selectedRunIds.length === 0 || deleteSelectedRunsMutation.isPending) {
      return;
    }

    deleteSelectedRunsMutation.mutate(
      { run_ids: selectedRunIds },
      {
        onSuccess: (response) => {
          setRunRowSelection({});
          setConfirmBulkDelete(false);
          setBulkDeleteStatus({
            body: [
              `${response.deleted_run_ids.length} ${response.deleted_run_ids.length === 1 ? "run was" : "runs were"} deleted.`,
              response.skipped_active_run_ids.length > 0
                ? `${response.skipped_active_run_ids.length} active ${response.skipped_active_run_ids.length === 1 ? "run was" : "runs were"} skipped.`
                : null,
              response.missing_run_ids.length > 0
                ? `${response.missing_run_ids.length} missing ${response.missing_run_ids.length === 1 ? "run was" : "runs were"} skipped.`
                : null,
            ]
              .filter(Boolean)
              .join(" "),
            status:
              response.skipped_active_run_ids.length > 0 || response.missing_run_ids.length > 0 ? "error" : "success",
            title:
              response.skipped_active_run_ids.length > 0 || response.missing_run_ids.length > 0
                ? "Bulk delete partially completed"
                : "Bulk delete completed",
          });
        },
        onError: () => {
          setBulkDeleteStatus({
            body: "Selected generation runs could not be deleted.",
            status: "error",
            title: "Bulk delete failed",
          });
        },
      },
    );
  }

  if (featureSummaryQuery.isPending || playlistsQuery.isPending || runsQuery.isPending) {
    return <EmptyStateCard body="Loading sonic generation state..." className={layoutClasses.emptyStateNarrow} title="Loading" />;
  }

  if (featureSummaryQuery.isError || playlistsQuery.isError || runsQuery.isError) {
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
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <MetricCard icon={AudioLines} label="Ready" toneClass="bg-ctp-green/10 text-ctp-green ring-ctp-green/25" value={summary.ready_tracks.toLocaleString()} />
        <MetricCard icon={Activity} label="Pending" toneClass="bg-ctp-yellow/10 text-ctp-yellow ring-ctp-yellow/25" value={summary.pending_tracks.toLocaleString()} />
        <MetricCard icon={DatabaseZap} label="Missing" toneClass="bg-ctp-red/10 text-ctp-red ring-ctp-red/25" value={summary.missing_tracks.toLocaleString()} />
        <MetricCard icon={CircleX} label="Failed" toneClass="bg-ctp-red/10 text-ctp-red ring-ctp-red/25" value={summary.failed_tracks.toLocaleString()} />
        <MetricCard icon={ListChecks} label="Total" toneClass="bg-ctp-blue/10 text-ctp-blue ring-ctp-blue/25" value={summary.total_tracks.toLocaleString()} />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className={textClasses.sectionTitle}>Playlist generator</h2>
          <p className={`mt-1 ${textClasses.bodyMuted}`}>
            Choose how the music should flow, preview the real proposed crates, then generate or save the setup as
            a reusable recipe.
          </p>
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
      {recipesQuery.isError ? (
        <StatusMessage
          body="Saved recipes could not be loaded. One-off preview and generation remain available."
          status="error"
          title="Recipes unavailable"
        />
      ) : null}

      <SavedRecipesPanel
        autoExport={recipeAutoExport}
        editingRecipeId={editingRecipeId}
        enabled={recipeEnabled}
        isDeleting={deleteRecipeMutation.isPending}
        isRegenerating={regenerateRecipeMutation.isPending}
        isSaving={createRecipeMutation.isPending || updateRecipeMutation.isPending}
        mutationStatus={recipeMutationStatus}
        name={recipeName}
        onAutoExportChange={setRecipeAutoExport}
        onCancelEdit={resetRecipeEditor}
        onDelete={handleDeleteRecipe}
        onEdit={loadRecipe}
        onEnabledChange={setRecipeEnabled}
        onExportProfileChange={setRecipeExportProfileId}
        onNameChange={setRecipeName}
        onRegenerate={handleRegenerateRecipe}
        onRegenerateOnChangeChange={setRecipeRegenerateOnChange}
        onSave={handleSaveRecipe}
        recipes={recipes}
        regenerateOnChange={recipeRegenerateOnChange}
        saveDisabled={!recipeName.trim() || sourceIsInvalid || (recipeAutoExport && recipeExportProfileId === null)}
        selectedExportProfileId={recipeExportProfileId}
        exportProfiles={exportProfiles}
      />

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
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className={textClasses.label}>Musical flow</h3>
            <p className={`mt-1 ${textClasses.caption}`}>
              Grouping finds compatible tracks; this separate intent decides the order inside each proposed crate.
            </p>
          </div>
          <ActionButton className={controlClasses.actionButtonCompact} onClick={resetAdaptiveDefaults} type="button">
            <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            Reset defaults
          </ActionButton>
        </div>

        <fieldset className="grid gap-2">
          <legend className={textClasses.label}>Sequencing intent</legend>
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
            {sequenceIntentOptions.map((option) => {
              const isSelected = sequenceIntent === option.value;
              return (
                <button
                  aria-pressed={isSelected}
                  className={`${surfaceClasses.rowCardCompact} text-left transition-colors ${
                    isSelected
                      ? "border-ctp-mauve/60 bg-ctp-mauve/10 ring-1 ring-ctp-mauve/20"
                      : "hover:border-ctp-surface2"
                  }`}
                  key={option.value}
                  onClick={() => setSequenceIntent(option.value)}
                  type="button"
                >
                  <span className={`block ${textClasses.title}`}>{option.label}</span>
                  <span className={`mt-1 block ${textClasses.caption}`}>{option.description}</span>
                </button>
              );
            })}
          </div>
        </fieldset>

        <div className="flex items-start justify-between gap-3 border-t border-ctp-surface1 pt-3">
          <div>
            <h3 className={textClasses.label}>Grouping recipe</h3>
            <p className={`mt-1 ${textClasses.caption}`}>{activePreset.description}</p>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <label className="grid gap-1.5">
            <span className={textClasses.label}>Preset</span>
            <select
              className={`${controlClasses.controlRadius} min-h-10 border border-ctp-surface1 bg-ctp-surface0 px-3 text-ctp-text outline-none ${textClasses.input}`}
              onChange={(event) => handlePresetChange(event.target.value as PresetKey)}
              value={presetKey}
            >
              {generationPresets.map((preset) => (
                <option key={preset.key} value={preset.key}>
                  {preset.label}
                </option>
              ))}
            </select>
          </label>
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
          <label className="grid gap-1.5">
            <span className={textClasses.label}>Naming</span>
            <select
              className={`${controlClasses.controlRadius} min-h-10 border border-ctp-surface1 bg-ctp-surface0 px-3 text-ctp-text outline-none ${textClasses.input}`}
              onChange={(event) => setNamingStrategy(event.target.value as NamingStrategy)}
              value={namingStrategy}
            >
              <option value="dj_utility_v1">DJ utility</option>
              <option value="crate_label_v1">Crate label</option>
              <option value="metadata_tagline_v1">Metadata tagline</option>
              <option value="functional_slot_v1">Functional slot</option>
            </select>
          </label>
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <NumericInput
            adaptiveValue={adaptiveNumericValues.maxDepth}
            fieldKey="maxDepth"
            onBlur={normalizeNumericDraft}
            onChange={updateNumericDraft}
            onReset={resetNumericDraft}
            onStep={stepNumericDraft}
            value={numericDrafts.maxDepth}
          />
          <NumericInput
            adaptiveValue={adaptiveNumericValues.targetPlaylistSize}
            fieldKey="targetPlaylistSize"
            onBlur={normalizeNumericDraft}
            onChange={updateNumericDraft}
            onReset={resetNumericDraft}
            onStep={stepNumericDraft}
            value={numericDrafts.targetPlaylistSize}
          />
          <NumericInput
            adaptiveValue={adaptiveNumericValues.minPlaylistSize}
            fieldKey="minPlaylistSize"
            onBlur={normalizeNumericDraft}
            onChange={updateNumericDraft}
            onReset={resetNumericDraft}
            onStep={stepNumericDraft}
            value={numericDrafts.minPlaylistSize}
          />
          <NumericInput
            adaptiveValue={adaptiveNumericValues.maxChildren}
            fieldKey="maxChildren"
            onBlur={normalizeNumericDraft}
            onChange={updateNumericDraft}
            onReset={resetNumericDraft}
            onStep={stepNumericDraft}
            value={numericDrafts.maxChildren}
          />
        </div>

        <button
          className="flex w-fit items-center gap-1.5 text-[12px] font-semibold text-ctp-subtext0 transition-colors hover:text-ctp-text"
          onClick={() => setAdvancedOpen((current) => !current)}
          type="button"
        >
          {advancedOpen ? (
            <ChevronDown aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
          ) : (
            <ChevronRight aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
          )}
          Advanced shape controls
        </button>

        {advancedOpen ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-7">
            <label className="grid gap-1.5">
              <span className={textClasses.label}>Ordering</span>
              <select
                className={`${controlClasses.controlRadius} min-h-10 border border-ctp-surface1 bg-ctp-surface0 px-3 text-ctp-text outline-none ${textClasses.input}`}
                onChange={(event) => setOrderingStrategy(event.target.value as OrderingStrategy)}
                value={orderingStrategy}
              >
                <option value="profile_nearest_neighbor_rolling_v2">Balanced flow</option>
                <option value="center_out_v1">Center out</option>
                <option value="seeded_shuffle_v1">Seeded shuffle</option>
              </select>
            </label>
            <label className="grid gap-1.5">
              <span className={textClasses.label}>Diversity</span>
              <select
                className={`${controlClasses.controlRadius} min-h-10 border border-ctp-surface1 bg-ctp-surface0 px-3 text-ctp-text outline-none ${textClasses.input}`}
                onChange={(event) => setDiversityMode(event.target.value as DiversityMode)}
                value={diversityMode}
              >
                <option value="balanced_v1">Balanced</option>
                <option value="loose_v1">Loose</option>
                <option value="strict_v1">Strict</option>
              </select>
            </label>
            <label className="grid gap-1.5">
              <span className={textClasses.label}>Tempo</span>
              <select
                className={`${controlClasses.controlRadius} min-h-10 border border-ctp-surface1 bg-ctp-surface0 px-3 text-ctp-text outline-none ${textClasses.input}`}
                onChange={(event) => setTempoMode(event.target.value as TempoMode)}
                value={tempoMode}
              >
                <option value="mixable_v1">Mixable BPM</option>
                <option value="raw_v1">Raw BPM</option>
              </select>
            </label>
            <label className="grid gap-1.5">
              <span className={textClasses.label}>Semantic audio</span>
              <select
                className={`${controlClasses.controlRadius} min-h-10 border border-ctp-surface1 bg-ctp-surface0 px-3 text-ctp-text outline-none ${textClasses.input}`}
                onChange={(event) => setSemanticMode(event.target.value as SemanticMode)}
                value={semanticMode}
              >
                <option value="off">Descriptors only</option>
                <option value="auto">Use when available</option>
              </select>
            </label>
            <label className="grid gap-1.5">
              <span className={textClasses.label}>Semantic weight</span>
              <input
                className={`${controlClasses.controlRadius} min-h-10 border border-ctp-surface1 bg-ctp-surface0 px-3 text-ctp-text outline-none ${textClasses.input}`}
                max={1}
                min={0}
                onChange={(event) => {
                  const nextValue = Number(event.currentTarget.value);
                  if (Number.isFinite(nextValue)) {
                    setSemanticWeight(Math.max(0, Math.min(1, nextValue)));
                  }
                }}
                step={0.05}
                type="number"
                value={semanticWeight}
              />
            </label>
            <label className="grid gap-1.5">
              <span className={textClasses.label}>Output</span>
              <select
                className={`${controlClasses.controlRadius} min-h-10 border border-ctp-surface1 bg-ctp-surface0 px-3 text-ctp-text outline-none ${textClasses.input}`}
                onChange={(event) => setOutputScope(event.target.value as OutputScope)}
                value={outputScope}
              >
                <option value="tree_v1">Tree</option>
                <option value="leaf_only_v1">Leaves only</option>
                <option value="top_level_v1">Top level</option>
              </select>
            </label>
            <NumericInput
              adaptiveValue={adaptiveNumericValues.randomSeed}
              fieldKey="randomSeed"
              onBlur={normalizeNumericDraft}
              onChange={updateNumericDraft}
              onReset={resetNumericDraft}
              onStep={stepNumericDraft}
              value={numericDrafts.randomSeed}
            />
          </div>
        ) : null}

        {preview && (preview.playlists?.length ?? 0) > 0 ? (
          <RealPlaylistPreview
            confidence={preview.confidence ?? null}
            coverage={preview.coverage ?? null}
            playlists={preview.playlists ?? []}
            skippedReasons={formatSkippedReasons(preview.skipped_reasons)}
            warnings={preview.warnings ?? []}
          />
        ) : preview?.projection ? (
          <GenerationProjection projection={preview.projection} />
        ) : null}
      </section>

      <section className={`${surfaceClasses.compactCard} grid gap-3`} aria-label="Generated run management">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className={textClasses.label}>Generated runs</h3>
            <p className={`mt-1 ${textClasses.caption}`}>{generationRuns.length.toLocaleString()} stored runs</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <ActionButton
              className={controlClasses.actionButtonCompact}
              disabled={!generationRuns.some((run) => run.status === "failed")}
              onClick={() => selectGenerationRuns((run) => run.status === "failed")}
              type="button"
            >
              Select failed
            </ActionButton>
            <ActionButton
              className={controlClasses.actionButtonCompact}
              disabled={!generationRuns.some((run) => run.status === "completed" && run.id !== latestCompletedRunId)}
              onClick={() => selectGenerationRuns((run) => run.status === "completed" && run.id !== latestCompletedRunId)}
              type="button"
            >
              Select old completed
            </ActionButton>
            <ActionButton
              className={controlClasses.actionButtonCompact}
              disabled={!generationRuns.some(isRunDeletable)}
              onClick={() => selectGenerationRuns(isRunDeletable)}
              type="button"
            >
              Select all deletable
            </ActionButton>
          </div>
        </div>

        {bulkDeleteStatus ? (
          <StatusMessage body={bulkDeleteStatus.body} status={bulkDeleteStatus.status} title={bulkDeleteStatus.title} />
        ) : null}

        {confirmBulkDelete ? (
          <section className={`${surfaceClasses.insetPanel} px-3 py-2`} aria-label="Delete selected generated runs confirmation">
            <p className={textClasses.label}>Delete {selectedRunIds.length.toLocaleString()} selected runs</p>
            <p className={`mt-1 ${textClasses.caption}`}>
              Generated playlists and generated playlist tracks for selected completed or failed runs will be removed.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <ActionButton
                className={`${controlClasses.actionButtonCompact} inline-flex items-center gap-1.5`}
                disabled={deleteSelectedRunsMutation.isPending}
                onClick={handleDeleteSelectedRuns}
                tone="danger"
                type="button"
              >
                <Trash2 aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
                {deleteSelectedRunsMutation.isPending ? "Deleting..." : "Confirm delete"}
              </ActionButton>
              <ActionButton
                className={controlClasses.actionButtonCompact}
                disabled={deleteSelectedRunsMutation.isPending}
                onClick={() => setConfirmBulkDelete(false)}
                type="button"
              >
                Cancel
              </ActionButton>
            </div>
          </section>
        ) : null}

        {generationRuns.length > 0 ? (
          <DataTable
            bulkActionSlot={
              <ActionButton
                className={`${controlClasses.actionButtonCompact} inline-flex items-center gap-1.5`}
                disabled={selectedRunIds.length === 0 || deleteSelectedRunsMutation.isPending}
                onClick={() => {
                  setBulkDeleteStatus(null);
                  setConfirmBulkDelete(true);
                }}
                tone="danger"
                type="button"
              >
                <Trash2 aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
                Delete selected
              </ActionButton>
            }
            columns={runColumns}
            data={generationRuns}
            density="tight"
            onActivate={(run) => navigate(`/generated-runs/${run.id}`)}
            onRowSelectionChange={setRunRowSelection}
            onSortingChange={setRunSorting}
            rowCanSelect={isRunDeletable}
            rowId={(run) => String(run.id)}
            rowSelection={runRowSelection}
            sorting={runSorting}
            stickyHeader
          />
        ) : (
          <EmptyStateCard body="Generated runs will appear here after playlist generation completes." className="text-left" title="No generated runs" />
        )}
      </section>
    </form>
  );
}

function SavedRecipesPanel({
  autoExport,
  editingRecipeId,
  enabled,
  exportProfiles,
  isDeleting,
  isRegenerating,
  isSaving,
  mutationStatus,
  name,
  onAutoExportChange,
  onCancelEdit,
  onDelete,
  onEdit,
  onEnabledChange,
  onExportProfileChange,
  onNameChange,
  onRegenerate,
  onRegenerateOnChangeChange,
  onSave,
  recipes,
  regenerateOnChange,
  saveDisabled,
  selectedExportProfileId,
}: {
  autoExport: boolean;
  editingRecipeId: number | null;
  enabled: boolean;
  exportProfiles: M3uExportProfile[];
  isDeleting: boolean;
  isRegenerating: boolean;
  isSaving: boolean;
  mutationStatus: RecipeMutationStatus | null;
  name: string;
  onAutoExportChange: (value: boolean) => void;
  onCancelEdit: () => void;
  onDelete: (recipe: PlaylistGenerationRecipe) => void;
  onEdit: (recipe: PlaylistGenerationRecipe) => void;
  onEnabledChange: (value: boolean) => void;
  onExportProfileChange: (profileId: number | null) => void;
  onNameChange: (value: string) => void;
  onRegenerate: (recipe: PlaylistGenerationRecipe) => void;
  onRegenerateOnChangeChange: (value: boolean) => void;
  onSave: () => void;
  recipes: PlaylistGenerationRecipe[];
  regenerateOnChange: boolean;
  saveDisabled: boolean;
  selectedExportProfileId: number | null;
}) {
  return (
    <section className={`${surfaceClasses.compactCard} grid gap-3`} aria-label="Saved generation recipes">
      <div>
        <h3 className={textClasses.label}>Saved recipes</h3>
        <p className={`mt-1 ${textClasses.caption}`}>
          Reuse a named musical setup against the latest eligible library. Regeneration creates a new immutable run.
        </p>
      </div>

      {mutationStatus ? (
        <StatusMessage body={mutationStatus.body} status={mutationStatus.status} title={mutationStatus.title} />
      ) : null}

      {recipes.length > 0 ? (
        <div className="grid gap-2 lg:grid-cols-2">
          {recipes.map((recipe) => (
            <article className={`${surfaceClasses.insetPanel} grid gap-2 p-3`} key={recipe.id}>
              <div className="flex min-w-0 items-start justify-between gap-3">
                <div className="min-w-0">
                  <h4 className={`truncate ${textClasses.title}`}>{recipe.name}</h4>
                  <p className={`mt-1 ${textClasses.caption}`}>
                    {recipe.enabled ? "Automation eligible" : "Manual only"}
                    {recipe.regenerate_on_change ? " · regenerates after relevant changes" : ""}
                    {recipe.export_config?.enabled ? " · leaf export refresh enabled" : ""}
                  </p>
                </div>
                <Pill tone={recipe.enabled ? "success" : "neutral"}>{recipe.enabled ? "Enabled" : "Paused"}</Pill>
              </div>
              <p className={textClasses.finePrint}>
                {recipe.last_run_id !== null
                  ? `Last run #${recipe.last_run_id}${
                      recipe.last_regenerated_at
                        ? ` · ${formatPlaylistTimestamp(recipe.last_regenerated_at)}`
                        : ""
                    }`
                  : "Not regenerated yet"}
              </p>
              <div className="flex flex-wrap gap-2">
                <ActionButton
                  className={controlClasses.actionButtonCompact}
                  disabled={isRegenerating}
                  onClick={() => onRegenerate(recipe)}
                  type="button"
                >
                  <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
                  Regenerate
                </ActionButton>
                <ActionButton
                  className={controlClasses.actionButtonCompact}
                  disabled={isSaving}
                  onClick={() => onEdit(recipe)}
                  type="button"
                >
                  Load and edit
                </ActionButton>
                <ActionButton
                  className={controlClasses.actionButtonCompact}
                  disabled={isDeleting}
                  onClick={() => onDelete(recipe)}
                  tone="danger"
                  type="button"
                >
                  <Trash2 aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
                  Delete
                </ActionButton>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className={textClasses.bodyMuted}>No saved recipes yet. Configure the source and musical flow below, then save it here.</p>
      )}

      <div className="grid gap-3 border-t border-ctp-surface1 pt-3 xl:grid-cols-[minmax(16rem,1fr)_auto] xl:items-end">
        <label className="grid gap-1.5" htmlFor="generation-recipe-name">
          <span className={textClasses.label}>{editingRecipeId === null ? "New recipe name" : "Editing recipe"}</span>
          <span className={`${controlClasses.searchFrame} flex min-h-10 items-center gap-2 px-2.5`}>
            <Save aria-hidden="true" className="h-4 w-4 shrink-0 text-ctp-mauve" />
            <input
              className={`min-w-0 flex-1 bg-transparent py-2 text-ctp-text outline-none placeholder:text-ctp-overlay1 ${textClasses.input}`}
              id="generation-recipe-name"
              onChange={(event) => onNameChange(event.currentTarget.value)}
              placeholder="Friday warm-up crates"
              type="text"
              value={name}
            />
          </span>
        </label>
        <div className="flex flex-wrap gap-2">
          {editingRecipeId !== null ? (
            <ActionButton disabled={isSaving} onClick={onCancelEdit} type="button">
              Cancel
            </ActionButton>
          ) : null}
          <ActionButton disabled={saveDisabled || isSaving} onClick={onSave} type="button">
            <Save aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            {isSaving ? "Saving…" : editingRecipeId === null ? "Save recipe" : "Update recipe"}
          </ActionButton>
        </div>
      </div>
      <div className="grid gap-2 md:grid-cols-3">
        <label className={`${surfaceClasses.insetPanel} flex items-start gap-2 p-3`}>
          <input
            checked={enabled}
            className="mt-0.5 h-4 w-4 accent-ctp-mauve"
            onChange={(event) => onEnabledChange(event.currentTarget.checked)}
            type="checkbox"
          />
          <span>
            <span className={`block ${textClasses.label}`}>Enabled</span>
            <span className={`mt-1 block ${textClasses.caption}`}>
              Make this recipe eligible for automatic regeneration. Manual regeneration remains available.
            </span>
          </span>
        </label>
        <label className={`${surfaceClasses.insetPanel} flex items-start gap-2 p-3`}>
          <input
            checked={regenerateOnChange}
            className="mt-0.5 h-4 w-4 accent-ctp-mauve"
            onChange={(event) => onRegenerateOnChangeChange(event.currentTarget.checked)}
            type="checkbox"
          />
          <span>
            <span className={`block ${textClasses.label}`}>Keep generated crates current</span>
            <span className={`mt-1 block ${textClasses.caption}`}>Regenerate after relevant library changes settle.</span>
          </span>
        </label>
        <label className={`${surfaceClasses.insetPanel} flex items-start gap-2 p-3`}>
          <input
            checked={autoExport}
            className="mt-0.5 h-4 w-4 accent-ctp-mauve"
            onChange={(event) => onAutoExportChange(event.currentTarget.checked)}
            type="checkbox"
          />
          <span>
            <span className={`block ${textClasses.label}`}>Refresh configured exports</span>
            <span className={`mt-1 block ${textClasses.caption}`}>
              Export leaf playlists only, avoiding redundant parent and child copies.
            </span>
          </span>
        </label>
      </div>
      {autoExport ? (
        <div className={`${surfaceClasses.insetPanel} grid gap-2 p-3 md:grid-cols-[minmax(14rem,1fr)_2fr] md:items-center`}>
          <label className="grid gap-1.5" htmlFor="generation-recipe-export-profile">
            <span className={textClasses.label}>Automatic export profile</span>
            <select
              className={`${controlClasses.controlRadius} min-h-10 border border-ctp-surface1 bg-ctp-surface0 px-3 text-ctp-text outline-none ${textClasses.input}`}
              id="generation-recipe-export-profile"
              onChange={(event) =>
                onExportProfileChange(event.currentTarget.value ? Number(event.currentTarget.value) : null)
              }
              value={selectedExportProfileId ?? ""}
            >
              <option value="">Choose an M3U export profile</option>
              {exportProfiles.map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {profile.name}
                  {profile.is_default ? " (default)" : ""}
                </option>
              ))}
            </select>
          </label>
          <p className={textClasses.caption}>
            The automatic export uses this profile’s library path, writes M3U8 files, and includes leaf playlists only.
            {exportProfiles.length === 0
              ? " Create an export profile in M3U export before enabling automatic refresh."
              : ""}
          </p>
        </div>
      ) : null}
    </section>
  );
}

function RealPlaylistPreview({
  confidence,
  coverage,
  playlists,
  skippedReasons,
  warnings,
}: {
  confidence: number | null;
  coverage: number | null;
  playlists: SonicPreviewPlaylist[];
  skippedReasons: string[];
  warnings: string[];
}) {
  return (
    <section className="grid gap-3 rounded-[8px] border border-ctp-mauve/35 bg-ctp-mauve/5 p-3" aria-label="Actual playlist preview">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h4 className={textClasses.title}>Actual proposed playlists</h4>
          <p className={`mt-1 ${textClasses.caption}`}>
            Names, tracks, boundaries, and quality evidence come from the real in-memory generator. Nothing is saved
            until you choose Generate.
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <span className={controlClasses.countBadge}>{playlists.length.toLocaleString()} playlists</span>
          {coverage !== null ? <span className={controlClasses.countBadge}>{formatEvidencePercent(coverage)} coverage</span> : null}
          {confidence !== null ? (
            <span className={controlClasses.countBadge}>{formatEvidencePercent(confidence)} confidence</span>
          ) : null}
        </div>
      </div>

      {warnings.length > 0 || skippedReasons.length > 0 ? (
        <div className="grid gap-2 md:grid-cols-2">
          {warnings.length > 0 ? <EvidenceNotes label="Warnings" notes={warnings} tone="warning" /> : null}
          {skippedReasons.length > 0 ? <EvidenceNotes label="Skipped" notes={skippedReasons} tone="neutral" /> : null}
        </div>
      ) : null}

      <div className="grid gap-3 xl:grid-cols-2">
        {playlists.map((playlist, index) => (
          <article className={`${surfaceClasses.insetPanel} grid gap-3 p-3`} key={`${playlist.name}-${index}`}>
            <div className="flex min-w-0 items-start justify-between gap-3">
              <div className="min-w-0">
                <h5 className={`truncate ${textClasses.title}`} title={playlist.name}>
                  {playlist.name}
                </h5>
                <p className={`mt-1 ${textClasses.caption}`}>
                  {playlist.size.toLocaleString()} tracks ·{" "}
                  {playlist.export_default ? "leaf export target" : "parent grouping"}
                  {` · ${sequenceIntentLabel(playlist.sequencing_intent)}`}
                </p>
              </div>
              <Pill tone={playlist.confidence >= 0.7 ? "success" : playlist.confidence >= 0.45 ? "pending" : "danger"}>
                {formatEvidencePercent(playlist.confidence)} confidence
              </Pill>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <PreviewStat
                label="Coverage"
                value={formatEvidencePercent(playlist.coverage)}
              />
              <PreviewStat label="Cohesion" value={formatEvidencePercent(playlist.cohesion)} />
              <PreviewStat label="Confidence" value={formatEvidencePercent(playlist.confidence)} />
            </div>
            <PreviewTrackList label="Representative tracks" tracks={playlist.representative_tracks} />
            <div className="grid gap-3 md:grid-cols-2">
              <PreviewTrackList emptyLabel="No boundary items flagged" label="Boundary items" tracks={playlist.boundary_tracks} />
              <PreviewTrackList emptyLabel="No outliers flagged" label="Outliers" tracks={playlist.outlier_tracks} />
            </div>
            {playlist.warnings.length > 0 || formatSkippedReasons(playlist.skipped_reasons).length > 0 ? (
              <div className="grid gap-2 md:grid-cols-2">
                {playlist.warnings.length > 0 ? (
                  <EvidenceNotes label="Warnings" notes={playlist.warnings} tone="warning" />
                ) : null}
                {formatSkippedReasons(playlist.skipped_reasons).length > 0 ? (
                  <EvidenceNotes
                    label="Skipped"
                    notes={formatSkippedReasons(playlist.skipped_reasons)}
                    tone="neutral"
                  />
                ) : null}
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}

function PreviewTrackList({
  emptyLabel,
  label,
  tracks,
}: {
  emptyLabel?: string;
  label: string;
  tracks: SonicPreviewTrack[];
}) {
  return (
    <div className="min-w-0">
      <p className={textClasses.label}>{label}</p>
      {tracks.length > 0 ? (
        <ul className="mt-1 grid gap-1">
          {tracks.map((track, index) => (
            <li className={`min-w-0 truncate ${textClasses.caption}`} key={`${track.local_track_id ?? "track"}-${index}`}>
              {track.artist ? `${track.artist} — ` : ""}
              {track.title ?? "Untitled track"}
            </li>
          ))}
        </ul>
      ) : (
        <p className={`mt-1 ${textClasses.finePrint}`}>{emptyLabel ?? "No tracks returned"}</p>
      )}
    </div>
  );
}

function EvidenceNotes({
  label,
  notes,
  tone,
}: {
  label: string;
  notes: string[];
  tone: "neutral" | "warning";
}) {
  return (
    <div className={`rounded-[7px] border p-2.5 ${tone === "warning" ? "border-ctp-yellow/30 bg-ctp-yellow/5" : "border-ctp-surface1 bg-ctp-surface0/40"}`}>
      <p className={`${textClasses.label} ${tone === "warning" ? "text-ctp-yellow" : ""}`}>{label}</p>
      <ul className="mt-1 grid gap-1">
        {notes.map((note, index) => (
          <li className={textClasses.caption} key={`${note}-${index}`}>
            {note}
          </li>
        ))}
      </ul>
    </div>
  );
}

function formatEvidencePercent(value: number) {
  const percentage = value <= 1 ? value * 100 : value;
  return `${Math.round(Math.max(0, Math.min(100, percentage)))}%`;
}

function formatSkippedReasons(reasons: Record<string, number> | string[] | undefined) {
  if (reasons === undefined) {
    return [];
  }
  if (Array.isArray(reasons)) {
    return reasons;
  }
  return Object.entries(reasons).map(([reason, count]) => `${humanizeEvidenceKey(reason)}: ${count.toLocaleString()}`);
}

function humanizeEvidenceKey(value: string) {
  return value.replace(/_/g, " ").replace(/^\w/, (character) => character.toUpperCase());
}

function sequenceIntentLabel(value: string) {
  return sequenceIntentOptions.find((option) => option.value === value)?.label ?? humanizeEvidenceKey(value);
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

function GenerationProjection({ projection }: { projection: PlaylistGenerationProjection }) {
  const depthSummary = Object.entries(projection.depth_counts)
    .sort(([left], [right]) => Number(left) - Number(right))
    .map(([depth, count]) => `D${Number(depth) + 1}: ${count}`)
    .join(", ");
  const sizeSummary =
    projection.size_min === projection.size_max
      ? projection.size_min.toLocaleString()
      : `${projection.size_min.toLocaleString()}-${projection.size_max.toLocaleString()}`;

  return (
    <section className="grid gap-3 rounded-[8px] border border-ctp-surface1 bg-ctp-surface0/45 p-3" aria-label="Generation projection">
      <div className="grid gap-2 md:grid-cols-4">
        <PreviewStat label="Projected playlists" value={projection.playlist_count} />
        <PreviewStat label="Leaf playlists" value={projection.leaf_playlist_count} />
        <PreviewStat label="Size range" value={sizeSummary} />
        <PreviewStat label="Depths" value={depthSummary || "Flat"} />
      </div>
      {projection.sample_names.length > 0 ? (
        <div className="flex flex-wrap gap-1.5" aria-label="Sample generated names">
          {projection.sample_names.map((name) => (
            <span className={`${controlClasses.countBadge} max-w-full truncate`} key={name}>
              {name}
            </span>
          ))}
        </div>
      ) : null}
      {projection.config_notes.length > 0 ? (
        <div className="grid gap-1" aria-label="Generation config notes">
          {projection.config_notes.map((note) => (
            <p className={textClasses.caption} key={note}>
              {note}
            </p>
          ))}
        </div>
      ) : null}
    </section>
  );
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
  adaptiveValue,
  fieldKey,
  onBlur,
  onChange,
  onReset,
  onStep,
  value,
}: {
  adaptiveValue: number;
  fieldKey: NumericConfigKey;
  onBlur: (key: NumericConfigKey) => void;
  onChange: (key: NumericConfigKey, value: string) => void;
  onReset: (key: NumericConfigKey) => void;
  onStep: (key: NumericConfigKey, direction: -1 | 1) => void;
  value: string;
}) {
  const spec = numericFieldSpecs[fieldKey];
  return (
    <div className="grid min-w-0 gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <label className={textClasses.label} htmlFor={`generation-${fieldKey}`}>
          {spec.label}
        </label>
        <span className={textClasses.caption}>Default {adaptiveValue.toLocaleString()}</span>
      </div>
      <div className={`${controlClasses.searchFrame} flex min-h-10 items-center overflow-hidden`}>
        <IconButton
          className="h-10 w-9 rounded-none border-0 bg-transparent"
          label={`Decrease ${spec.label}`}
          onClick={() => onStep(fieldKey, -1)}
        >
          <Minus aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
        </IconButton>
        <input
          className={`min-h-10 min-w-0 flex-1 bg-transparent px-2 text-center text-ctp-text outline-none ${textClasses.input}`}
          id={`generation-${fieldKey}`}
          inputMode="numeric"
          max={spec.max}
          min={spec.min}
          onBlur={() => onBlur(fieldKey)}
          onChange={(event) => onChange(fieldKey, event.target.value)}
          step={spec.step}
          type="number"
          value={value}
        />
        <IconButton
          className="h-10 w-9 rounded-none border-0 bg-transparent"
          label={`Increase ${spec.label}`}
          onClick={() => onStep(fieldKey, 1)}
        >
          <Plus aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
        </IconButton>
        <IconButton
          className="h-10 w-9 rounded-none border-0 bg-transparent"
          label={`Reset ${spec.label}`}
          onClick={() => onReset(fieldKey)}
        >
          <Undo2 aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
        </IconButton>
      </div>
      <p className={textClasses.caption}>{spec.impact}</p>
    </div>
  );
}

function numericValuesToDrafts(values: NumericValues): NumericDrafts {
  return {
    maxChildren: String(values.maxChildren),
    maxDepth: String(values.maxDepth),
    minPlaylistSize: String(values.minPlaylistSize),
    randomSeed: String(values.randomSeed),
    targetPlaylistSize: String(values.targetPlaylistSize),
  };
}

function normalizeNumericDrafts(drafts: NumericDrafts, defaults: NumericValues): NumericValues {
  return {
    maxChildren: normalizeNumericValue("maxChildren", drafts.maxChildren, defaults.maxChildren),
    maxDepth: normalizeNumericValue("maxDepth", drafts.maxDepth, defaults.maxDepth),
    minPlaylistSize: normalizeNumericValue("minPlaylistSize", drafts.minPlaylistSize, defaults.minPlaylistSize),
    randomSeed: normalizeNumericValue("randomSeed", drafts.randomSeed, defaults.randomSeed),
    targetPlaylistSize: normalizeNumericValue("targetPlaylistSize", drafts.targetPlaylistSize, defaults.targetPlaylistSize),
  };
}

function normalizeNumericValue(key: NumericConfigKey, value: string, fallback: number) {
  const spec = numericFieldSpecs[key];
  if (value.trim() === "") {
    return clampNumber(fallback, spec.min, spec.max);
  }
  const parsedValue = Number(value);
  if (!Number.isFinite(parsedValue)) {
    return clampNumber(fallback, spec.min, spec.max);
  }
  return clampNumber(Math.round(parsedValue), spec.min, spec.max);
}

function clampNumber(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function readStringValue(value: unknown, fallback: string) {
  return typeof value === "string" ? value : fallback;
}

function readNumberValue(value: unknown, fallback: number) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function readStringOption<TValue extends string>(
  value: unknown,
  options: ReadonlyArray<{ value: TValue }>,
  fallback: TValue,
) {
  return typeof value === "string" && options.some((option) => option.value === value)
    ? (value as TValue)
    : fallback;
}

function adaptiveNumericDefaults(readyTrackCount: number, presetKey: PresetKey): NumericValues {
  const ready = Math.max(0, Math.round(readyTrackCount));
  const target = clampNumber(Math.round(Math.sqrt(Math.max(ready, 1)) * 2.2), 24, 48);
  const min = clampNumber(Math.round(target * 0.35), 6, 18);
  const defaults: NumericValues = {
    maxChildren: ready < 500 ? 4 : 5,
    maxDepth: ready < 180 ? 2 : 3,
    minPlaylistSize: min,
    randomSeed: 42,
    targetPlaylistSize: target,
  };

  if (presetKey === "set_builder_v1") {
    return {
      ...defaults,
      maxChildren: 3,
      maxDepth: 2,
      minPlaylistSize: clampNumber(Math.round(target * 0.45), 8, 22),
      targetPlaylistSize: Math.max(target, 32),
    };
  }
  if (presetKey === "discovery_sampler_v1") {
    return {
      ...defaults,
      maxChildren: 5,
      maxDepth: 2,
      minPlaylistSize: clampNumber(Math.round(target * 0.3), 6, 14),
    };
  }
  if (presetKey === "metadata_collections_v1") {
    return {
      ...defaults,
      maxChildren: 6,
      maxDepth: 2,
      minPlaylistSize: clampNumber(Math.round(target * 0.4), 10, 20),
      targetPlaylistSize: Math.max(target, 36),
    };
  }
  if (presetKey === "micro_crates_v1") {
    const microTarget = clampNumber(Math.round(Math.sqrt(Math.max(ready, 1)) * 1.35), 10, 18);
    return {
      ...defaults,
      maxChildren: ready >= 180 ? 6 : 4,
      maxDepth: ready >= 80 ? 3 : 2,
      minPlaylistSize: clampNumber(Math.round(microTarget * 0.35), 4, 8),
      targetPlaylistSize: microTarget,
    };
  }
  return defaults;
}
