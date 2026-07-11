import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Eye, FileDown, FileText, Folder, Music2, Plus, Search } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ActionButton } from "../../components/ActionButton";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { StatusMessage } from "../../components/StatusMessage";
import { setSessionDraftCodec, useSessionDraftState } from "../../lib/useSessionDraftState";
import { controlClasses, layoutClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import { type PlaylistGenerationRun, useSonicRunsQuery } from "../sonic/queries";
import {
  createM3uExportProfile,
  exportFullRekordboxXml,
  exportM3uZip,
  exportRekordboxXml,
  playlistQueryKeys,
  previewM3uExport,
  type M3uExportFormat,
  type M3uExportPathFormat,
  type M3uExportPreviewResponse,
  type M3uExportProfile,
  type M3uExportRequest,
  type StreamingPlaylist,
  useM3uExportProfilesQuery,
  useStreamingPlaylistsQuery,
} from "./queries";

const emptyPlaylists: StreamingPlaylist[] = [];
const emptyProfiles: M3uExportProfile[] = [];
const emptyGeneratedRuns: PlaylistGenerationRun[] = [];
const numberSetSessionDraftCodec = setSessionDraftCodec<number>();
const exportFormatSetSessionDraftCodec = setSessionDraftCodec<M3uExportFormat>();
const exportDraftKey = (field: string) => `crate-lynx:playlist-export:v1:${field}`;
const exportFormatOptions = [
  { label: ".m3u", value: "m3u" },
  { label: ".m3u8", value: "m3u8" },
] as const satisfies readonly { label: string; value: M3uExportFormat }[];
const exportPathFormatOptions = [
  { label: "File URLs", value: "file_url" },
  { label: "Absolute paths", value: "absolute" },
] as const satisfies readonly { label: string; value: M3uExportPathFormat }[];

function downloadBlob(blob: Blob, filename: string) {
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");

  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
}

function playlistMatchesSearch(playlist: StreamingPlaylist, searchQuery: string) {
  const normalizedQuery = searchQuery.trim().toLowerCase();
  if (!normalizedQuery) {
    return true;
  }

  return playlist.title.toLowerCase().includes(normalizedQuery);
}

function getPreviewKey(request: M3uExportRequest | null) {
  if (request === null) {
    return null;
  }

  return JSON.stringify(request);
}

function buildExportRequest({
  formats,
  generatedRunIds,
  libraryPath,
  pathFormat,
  playlistIds,
  selectedProfileId,
}: {
  formats: M3uExportFormat[];
  generatedRunIds: number[];
  libraryPath: string;
  pathFormat: M3uExportPathFormat;
  playlistIds: number[];
  selectedProfileId: number | null;
}): M3uExportRequest | null {
  if ((playlistIds.length === 0 && generatedRunIds.length === 0) || formats.length === 0) {
    return null;
  }

  if (selectedProfileId !== null) {
    const request: M3uExportRequest = {
      formats,
      path_format: pathFormat,
      playlist_ids: playlistIds,
      profile_id: selectedProfileId,
    };
    if (generatedRunIds.length > 0) {
      request.generated_run_ids = generatedRunIds;
    }
    return request;
  }

  const trimmedLibraryPath = libraryPath.trim();
  if (!trimmedLibraryPath) {
    return null;
  }

  const request: M3uExportRequest = {
    formats,
    library_path: trimmedLibraryPath,
    path_format: pathFormat,
    playlist_ids: playlistIds,
  };
  if (generatedRunIds.length > 0) {
    request.generated_run_ids = generatedRunIds;
  }
  return request;
}

function buildFullRekordboxXmlRequest({
  libraryPath,
  pathFormat,
  selectedProfileId,
}: {
  libraryPath: string;
  pathFormat: M3uExportPathFormat;
  selectedProfileId: number | null;
}): M3uExportRequest | null {
  if (selectedProfileId !== null) {
    return {
      formats: ["m3u"],
      path_format: pathFormat,
      playlist_ids: [],
      profile_id: selectedProfileId,
    };
  }

  const trimmedLibraryPath = libraryPath.trim();
  if (!trimmedLibraryPath) {
    return null;
  }

  return {
    formats: ["m3u"],
    library_path: trimmedLibraryPath,
    path_format: pathFormat,
    playlist_ids: [],
  };
}

function ExportProfileSelector({
  libraryPath,
  onCreateProfile,
  onLibraryPathChange,
  onProfileChange,
  profileName,
  profiles,
  selectedProfileId,
  setProfileName,
}: {
  libraryPath: string;
  onCreateProfile: () => void;
  onLibraryPathChange: (path: string) => void;
  onProfileChange: (profileId: number | null) => void;
  profileName: string;
  profiles: M3uExportProfile[];
  selectedProfileId: number | null;
  setProfileName: (name: string) => void;
}) {
  const selectedProfile = profiles.find((profile) => profile.id === selectedProfileId) ?? null;
  const isCustomPath = selectedProfile === null;

  return (
    <section className={`${surfaceClasses.compactCard} grid gap-3`} aria-label="M3U export profile">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className={textClasses.sectionTitle}>Export target</h2>
          <p className={`mt-1 ${textClasses.bodyMuted}`}>
            {selectedProfile ? selectedProfile.name : "Custom path"}
          </p>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <label className={textClasses.label} htmlFor="m3u-export-profile">
            Profile
          </label>
          <select
            className={`${controlClasses.controlRadius} min-h-10 border border-ctp-surface1 bg-ctp-surface0 px-3 text-ctp-text outline-none ${textClasses.input}`}
            id="m3u-export-profile"
            onChange={(event) => {
              const value = event.target.value;
              onProfileChange(value === "custom" ? null : Number(value));
            }}
            value={selectedProfileId ?? "custom"}
          >
            {profiles.map((profile) => (
              <option key={profile.id} value={profile.id}>
                {profile.name}
                {profile.is_default ? " (default)" : ""}
              </option>
            ))}
            <option value="custom">Custom path</option>
          </select>
        </div>
      </div>

      <div className="grid gap-2 lg:grid-cols-[1fr_auto] lg:items-end">
        <label className="grid gap-1.5" htmlFor="m3u-export-library-path">
          <span className={textClasses.label}>Music library path</span>
          <span className={`${controlClasses.searchFrame} flex min-h-10 items-center gap-2 px-2.5`}>
            <Folder aria-hidden="true" className="h-4 w-4 shrink-0 text-ctp-mauve" />
            <input
              className={`min-w-0 flex-1 bg-transparent py-2 font-mono text-ctp-text outline-none placeholder:text-ctp-overlay1 ${textClasses.input}`}
              disabled={!isCustomPath}
              id="m3u-export-library-path"
              onChange={(event) => onLibraryPathChange(event.target.value)}
              placeholder="/mnt/music"
              type="text"
              value={selectedProfile?.library_path ?? libraryPath}
            />
          </span>
        </label>
        {isCustomPath ? (
          <div className="grid gap-1.5 sm:min-w-[18rem]">
            <label className={textClasses.label} htmlFor="m3u-export-profile-name">
              Profile name
            </label>
            <div className={`${controlClasses.searchFrame} flex min-h-10 items-center gap-2 px-2.5`}>
              <Plus aria-hidden="true" className="h-4 w-4 shrink-0 text-ctp-mauve" />
              <input
                className={`min-w-0 flex-1 bg-transparent py-2 text-ctp-text outline-none placeholder:text-ctp-overlay1 ${textClasses.input}`}
                id="m3u-export-profile-name"
                onChange={(event) => setProfileName(event.target.value)}
                placeholder="NAS export"
                type="text"
                value={profileName}
              />
              <ActionButton disabled={!libraryPath.trim() || !profileName.trim()} onClick={onCreateProfile} type="button">
                Save
              </ActionButton>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function ExportFormatSelector({
  selectedFormats,
  setSelectedFormats,
}: {
  selectedFormats: Set<M3uExportFormat>;
  setSelectedFormats: (formats: Set<M3uExportFormat>) => void;
}) {
  function toggleFormat(format: M3uExportFormat) {
    const nextFormats = new Set(selectedFormats);
    if (nextFormats.has(format)) {
      nextFormats.delete(format);
    } else {
      nextFormats.add(format);
    }
    setSelectedFormats(nextFormats);
  }

  return (
    <section className={`${surfaceClasses.compactCard} grid gap-3`} aria-label="M3U export formats">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className={textClasses.sectionTitle}>Formats</h2>
          <p className={`mt-1 ${textClasses.bodyMuted}`}>{selectedFormats.size} selected</p>
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {exportFormatOptions.map((option) => {
          const isSelected = selectedFormats.has(option.value);

          return (
            <label
              className={`${surfaceClasses.rowCardCompact} cursor-pointer transition-colors ${
                isSelected ? "border-ctp-green/45 bg-ctp-green/10" : "hover:border-ctp-surface2"
              }`}
              key={option.value}
            >
              <input
                checked={isSelected}
                className="sr-only"
                onChange={() => toggleFormat(option.value)}
                type="checkbox"
              />
              <span className="flex min-w-0 items-center gap-3">
                <span
                  aria-hidden="true"
                  className={`${controlClasses.iconFrame} h-8 w-8 shrink-0 ${
                    isSelected ? "border-ctp-green/45 text-ctp-green" : ""
                  }`}
                >
                  {isSelected ? <Check className="h-4 w-4" /> : <FileText className="h-4 w-4" />}
                </span>
                <span className={`font-mono ${textClasses.title}`}>{option.label}</span>
              </span>
            </label>
          );
        })}
      </div>
    </section>
  );
}

function ExportPathFormatSelector({
  pathFormat,
  setPathFormat,
}: {
  pathFormat: M3uExportPathFormat;
  setPathFormat: (pathFormat: M3uExportPathFormat) => void;
}) {
  return (
    <section className={`${surfaceClasses.compactCard} grid gap-3`} aria-label="M3U path style">
      <div>
        <h2 className={textClasses.sectionTitle}>Path style</h2>
        <p className={`mt-1 ${textClasses.bodyMuted}`}>
          {exportPathFormatOptions.find((option) => option.value === pathFormat)?.label}
        </p>
      </div>
      <div
        aria-label="Path style"
        className={`${controlClasses.controlRadius} inline-flex min-h-10 w-fit border border-ctp-surface1 bg-ctp-surface0 p-1`}
        role="group"
      >
        {exportPathFormatOptions.map((option) => {
          const isSelected = option.value === pathFormat;

          return (
            <button
              aria-pressed={isSelected}
              className={`${controlClasses.controlRadius} min-h-8 px-3 text-sm font-semibold transition-colors ${
                isSelected ? "bg-ctp-mauve text-ctp-base" : "text-ctp-subtext0 hover:bg-ctp-surface1 hover:text-ctp-text"
              }`}
              key={option.value}
              onClick={() => setPathFormat(option.value)}
              type="button"
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </section>
  );
}

function PlaylistSelectionList({
  playlists,
  searchQuery,
  selectedPlaylistIds,
  setSearchQuery,
  setSelectedPlaylistIds,
}: {
  playlists: StreamingPlaylist[];
  searchQuery: string;
  selectedPlaylistIds: Set<number>;
  setSearchQuery: (query: string) => void;
  setSelectedPlaylistIds: (playlistIds: Set<number>) => void;
}) {
  const filteredPlaylists = playlists.filter((playlist) => playlistMatchesSearch(playlist, searchQuery));
  const selectedCount = playlists.filter((playlist) => selectedPlaylistIds.has(playlist.id)).length;

  function togglePlaylist(playlistId: number) {
    const nextSelection = new Set(selectedPlaylistIds);
    if (nextSelection.has(playlistId)) {
      nextSelection.delete(playlistId);
    } else {
      nextSelection.add(playlistId);
    }
    setSelectedPlaylistIds(nextSelection);
  }

  return (
    <section className="grid shrink-0 gap-3" aria-label="Playlist export selection">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className={textClasses.sectionTitle}>Playlists</h2>
          <p className={`mt-1 ${textClasses.bodyMuted}`}>
            {selectedCount} of {playlists.length} selected
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            className={controlClasses.actionButtonCompact}
            onClick={() => setSelectedPlaylistIds(new Set(playlists.map((playlist) => playlist.id)))}
            type="button"
          >
            All
          </ActionButton>
          <ActionButton className={controlClasses.actionButtonCompact} onClick={() => setSelectedPlaylistIds(new Set())} type="button">
            None
          </ActionButton>
        </div>
      </div>

      <div className={`${controlClasses.searchFrame} flex min-h-10 items-center gap-2 px-2.5`}>
        <Search aria-hidden="true" className="h-4 w-4 shrink-0 text-ctp-mauve" />
        <input
          className={`min-w-0 flex-1 bg-transparent py-2 text-ctp-text outline-none placeholder:text-ctp-overlay1 ${textClasses.input}`}
          onChange={(event) => setSearchQuery(event.target.value)}
          placeholder="Search playlists"
          type="search"
          value={searchQuery}
        />
      </div>

      <div className="max-h-[28rem] overflow-y-auto pr-1">
        <div className="grid gap-2.5">
          {filteredPlaylists.map((playlist) => {
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
                <span className="flex min-w-0 items-center gap-3">
                  <span
                    aria-hidden="true"
                    className={`${controlClasses.iconFrame} h-8 w-8 shrink-0 ${
                      isSelected ? "border-ctp-green/45 text-ctp-green" : ""
                    }`}
                  >
                    {isSelected ? <Check className="h-4 w-4" /> : <Music2 className="h-4 w-4" />}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={`block truncate ${textClasses.title}`}>{playlist.title}</span>
                    <span className={`mt-1 block ${textClasses.caption}`}>
                      {playlist.imported_track_count.toLocaleString()} imported tracks
                    </span>
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function GeneratedRunSelectionList({
  generatedRuns,
  selectedGeneratedRunIds,
  setSelectedGeneratedRunIds,
}: {
  generatedRuns: PlaylistGenerationRun[];
  selectedGeneratedRunIds: Set<number>;
  setSelectedGeneratedRunIds: (runIds: Set<number>) => void;
}) {
  const selectedCount = generatedRuns.filter((run) => selectedGeneratedRunIds.has(run.id)).length;

  function toggleRun(runId: number) {
    const nextSelection = new Set(selectedGeneratedRunIds);
    if (nextSelection.has(runId)) {
      nextSelection.delete(runId);
    } else {
      nextSelection.add(runId);
    }
    setSelectedGeneratedRunIds(nextSelection);
  }

  if (generatedRuns.length === 0) {
    return null;
  }

  return (
    <section className="grid shrink-0 gap-3" aria-label="Generated run export selection">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className={textClasses.sectionTitle}>Generated runs</h2>
          <p className={`mt-1 ${textClasses.bodyMuted}`}>
            {selectedCount} of {generatedRuns.length} selected
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            className={controlClasses.actionButtonCompact}
            onClick={() => setSelectedGeneratedRunIds(new Set(generatedRuns.map((run) => run.id)))}
            type="button"
          >
            All
          </ActionButton>
          <ActionButton className={controlClasses.actionButtonCompact} onClick={() => setSelectedGeneratedRunIds(new Set())} type="button">
            None
          </ActionButton>
        </div>
      </div>
      <div className="max-h-[28rem] overflow-y-auto pr-1">
        <div className="grid gap-2.5 md:grid-cols-2">
          {generatedRuns.map((run) => {
            const isSelected = selectedGeneratedRunIds.has(run.id);

            return (
              <button
                className={`${surfaceClasses.rowCardCompact} text-left transition-colors ${
                  isSelected ? "border-ctp-green/45 bg-ctp-green/10" : "hover:border-ctp-surface2"
                }`}
                key={run.id}
                onClick={() => toggleRun(run.id)}
                type="button"
              >
                <span className="flex min-w-0 items-center gap-3">
                  <span
                    aria-hidden="true"
                    className={`${controlClasses.iconFrame} h-8 w-8 shrink-0 ${
                      isSelected ? "border-ctp-green/45 text-ctp-green" : ""
                    }`}
                  >
                    {isSelected ? <Check className="h-4 w-4" /> : <Folder className="h-4 w-4" />}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={`block truncate ${textClasses.title}`}>Generation {run.generation_number}</span>
                    <span className={`mt-1 block ${textClasses.caption}`}>
                      Run ID {run.id.toLocaleString()} · {run.playlist_count.toLocaleString()} playlists ·{" "}
                      {run.track_count.toLocaleString()} tracks · {run.status}
                    </span>
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function ExportPreview({ preview }: { preview: M3uExportPreviewResponse }) {
  const samplePath = preview.playlists.find((playlist) => playlist.sample_path !== null)?.sample_path ?? "No linked tracks selected";

  return (
    <section className={`${surfaceClasses.compactCard} grid gap-3`} aria-label="M3U export preview">
      <div className="flex flex-wrap gap-2">
        <span className={`${controlClasses.countBadge} min-w-fit px-2.5 py-1`}>
          {preview.playlist_count.toLocaleString()} playlists
        </span>
        <span className={`${controlClasses.countBadge} min-w-fit px-2.5 py-1 text-ctp-green`}>
          {preview.total_exported_track_count.toLocaleString()} tracks
        </span>
        <span className={`${controlClasses.countBadge} min-w-fit px-2.5 py-1 text-ctp-yellow`}>
          {preview.total_skipped_track_count.toLocaleString()} skipped
        </span>
      </div>
      <div>
        <p className={textClasses.label}>Sample path</p>
        <p className={`mt-1 break-all font-mono ${textClasses.input}`}>{samplePath}</p>
      </div>
      <div className="grid gap-2">
        {preview.playlists.slice(0, 5).map((playlist) => (
          <div
            className="flex min-w-0 flex-wrap items-center justify-between gap-2"
            key={`${playlist.source}-${playlist.playlist_id ?? playlist.generated_playlist_id}`}
          >
            <span className={`min-w-0 truncate ${textClasses.bodyRelaxed}`}>{playlist.title}</span>
            <span className={`font-mono ${textClasses.caption}`}>
              {playlist.archive_paths.join(" + ")}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

export function PlaylistM3uExportView() {
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const playlistsQuery = useStreamingPlaylistsQuery();
  const generatedRunsQuery = useSonicRunsQuery();
  const profilesQuery = useM3uExportProfilesQuery();
  const playlists = playlistsQuery.data?.playlists ?? emptyPlaylists;
  const generatedRuns = generatedRunsQuery.data?.runs ?? emptyGeneratedRuns;
  const profiles = profilesQuery.data?.profiles ?? emptyProfiles;
  const [selectedProfileId, setSelectedProfileId] = useSessionDraftState<number | null>(
    exportDraftKey("profile-id"),
    null,
  );
  const [libraryPath, setLibraryPath] = useSessionDraftState(exportDraftKey("library-path"), "");
  const [profileName, setProfileName] = useSessionDraftState(exportDraftKey("profile-name"), "Default export");
  const [searchQuery, setSearchQuery] = useSessionDraftState(exportDraftKey("search"), "");
  const [pathFormat, setPathFormat] = useSessionDraftState<M3uExportPathFormat>(
    exportDraftKey("path-format"),
    "file_url",
  );
  const [selectedFormats, setSelectedFormats] = useSessionDraftState<Set<M3uExportFormat>>(
    exportDraftKey("formats"),
    () => new Set(exportFormatOptions.map((option) => option.value)),
    exportFormatSetSessionDraftCodec,
  );
  const [selectedPlaylistIds, setSelectedPlaylistIds, hasStoredPlaylistSelection] = useSessionDraftState<Set<number>>(
    exportDraftKey("playlist-ids"),
    () => new Set(),
    numberSetSessionDraftCodec,
  );
  const [selectedGeneratedRunIds, setSelectedGeneratedRunIds, hasStoredGeneratedRunSelection] = useSessionDraftState<Set<number>>(
    exportDraftKey("generated-run-ids"),
    () => new Set(),
    numberSetSessionDraftCodec,
  );
  const [hasSeededSelection, setHasSeededSelection] = useState(false);
  const [lastPreviewKey, setLastPreviewKey] = useState<string | null>(null);
  const selectedFormatList = useMemo(
    () => exportFormatOptions.filter((option) => selectedFormats.has(option.value)).map((option) => option.value),
    [selectedFormats],
  );
  const selectedPlaylistIdList = useMemo(
    () => playlists.filter((playlist) => selectedPlaylistIds.has(playlist.id)).map((playlist) => playlist.id),
    [playlists, selectedPlaylistIds],
  );
  const exportableGeneratedRuns = useMemo(
    () => generatedRuns.filter((run) => run.playlist_count > 0),
    [generatedRuns],
  );
  const selectedGeneratedRunIdList = useMemo(
    () => exportableGeneratedRuns.filter((run) => selectedGeneratedRunIds.has(run.id)).map((run) => run.id),
    [exportableGeneratedRuns, selectedGeneratedRunIds],
  );
  const selectedExportTargetCount = selectedPlaylistIdList.length + selectedGeneratedRunIdList.length;
  const exportRequest = useMemo(
    () =>
      buildExportRequest({
        formats: selectedFormatList,
        generatedRunIds: selectedGeneratedRunIdList,
        libraryPath,
        pathFormat,
        playlistIds: selectedPlaylistIdList,
        selectedProfileId,
      }),
    [
      libraryPath,
      pathFormat,
      selectedFormatList,
      selectedGeneratedRunIdList,
      selectedPlaylistIdList,
      selectedProfileId,
    ],
  );
  const fullRekordboxXmlRequest = useMemo(
    () =>
      buildFullRekordboxXmlRequest({
        libraryPath,
        pathFormat,
        selectedProfileId,
      }),
    [libraryPath, pathFormat, selectedProfileId],
  );
  const exportRequestKey = getPreviewKey(exportRequest);
  const previewMutation = useMutation({
    mutationFn: previewM3uExport,
    onSuccess: (_data, variables) => setLastPreviewKey(getPreviewKey(variables)),
  });
  const exportMutation = useMutation({
    mutationFn: exportM3uZip,
    onSuccess: ({ blob, filename }) => {
      downloadBlob(blob, filename);
      void queryClient.invalidateQueries({ queryKey: playlistQueryKeys.m3uExportProfiles() });
    },
  });
  const rekordboxXmlMutation = useMutation({
    mutationFn: exportRekordboxXml,
    onSuccess: ({ blob, filename }) => {
      downloadBlob(blob, filename);
      void queryClient.invalidateQueries({ queryKey: playlistQueryKeys.m3uExportProfiles() });
    },
  });
  const fullRekordboxXmlMutation = useMutation({
    mutationFn: exportFullRekordboxXml,
    onSuccess: ({ blob, filename }) => {
      downloadBlob(blob, filename);
      void queryClient.invalidateQueries({ queryKey: playlistQueryKeys.m3uExportProfiles() });
    },
  });
  const createProfileMutation = useMutation({
    mutationFn: createM3uExportProfile,
    onSuccess: (profile) => {
      setSelectedProfileId(profile.id);
      setLibraryPath(profile.library_path);
      void queryClient.invalidateQueries({ queryKey: playlistQueryKeys.m3uExportProfiles() });
    },
  });
  const isPreviewCurrent = previewMutation.data !== undefined && lastPreviewKey === exportRequestKey;

  useEffect(() => {
    if (profiles.length === 0 || selectedProfileId !== null) {
      return;
    }

    const defaultProfile = profiles.find((profile) => profile.is_default) ?? profiles[0];
    setSelectedProfileId(defaultProfile.id);
    setLibraryPath(defaultProfile.library_path);
  }, [profiles, selectedProfileId, setLibraryPath, setSelectedProfileId]);

  useEffect(() => {
    if (hasSeededSelection || playlistsQuery.isPending || generatedRunsQuery.isPending) {
      return;
    }

    const requestedGeneratedRunId = Number(searchParams.get("generated_run"));
    const requestedGeneratedRun = exportableGeneratedRuns.find((run) => run.id === requestedGeneratedRunId);
    const requestedPlaylistId = Number(searchParams.get("playlist"));
    const requestedPlaylist = playlists.find((playlist) => playlist.id === requestedPlaylistId);
    if (requestedGeneratedRun) {
      setSelectedPlaylistIds(new Set());
      setSelectedGeneratedRunIds(new Set([requestedGeneratedRun.id]));
    } else if (Number.isFinite(requestedGeneratedRunId) && requestedGeneratedRunId > 0) {
      setSelectedPlaylistIds(new Set());
      setSelectedGeneratedRunIds(new Set());
    } else if (requestedPlaylist) {
      setSelectedPlaylistIds(new Set([requestedPlaylist.id]));
      setSelectedGeneratedRunIds(new Set());
    } else if (!hasStoredPlaylistSelection && !hasStoredGeneratedRunSelection) {
      setSelectedPlaylistIds(new Set(playlists.map((playlist) => playlist.id)));
      setSelectedGeneratedRunIds(new Set());
    }
    setHasSeededSelection(true);
  }, [
    exportableGeneratedRuns,
    generatedRunsQuery.isPending,
    hasStoredGeneratedRunSelection,
    hasStoredPlaylistSelection,
    hasSeededSelection,
    playlists,
    playlistsQuery.isPending,
    searchParams,
    setSelectedGeneratedRunIds,
    setSelectedPlaylistIds,
  ]);

  function handleProfileChange(profileId: number | null) {
    setSelectedProfileId(profileId);
    const profile = profiles.find((candidate) => candidate.id === profileId);
    if (profile !== undefined) {
      setLibraryPath(profile.library_path);
    }
  }

  function handleCreateProfile() {
    if (!libraryPath.trim() || !profileName.trim() || createProfileMutation.isPending) {
      return;
    }

    createProfileMutation.mutate({
      is_default: profiles.length === 0,
      library_path: libraryPath.trim(),
      name: profileName.trim(),
    });
  }

  function handlePreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (exportRequest === null || previewMutation.isPending) {
      return;
    }

    previewMutation.mutate(exportRequest);
  }

  function handleExport() {
    if (exportRequest === null || !isPreviewCurrent || exportMutation.isPending) {
      return;
    }

    exportMutation.mutate(exportRequest);
  }

  function handleRekordboxXmlExport() {
    if (exportRequest === null || !isPreviewCurrent || rekordboxXmlMutation.isPending) {
      return;
    }

    rekordboxXmlMutation.mutate(exportRequest);
  }

  function handleFullRekordboxXmlExport() {
    if (fullRekordboxXmlRequest === null || fullRekordboxXmlMutation.isPending) {
      return;
    }

    fullRekordboxXmlMutation.mutate(fullRekordboxXmlRequest);
  }

  if (playlistsQuery.isPending || generatedRunsQuery.isPending || profilesQuery.isPending) {
    return <EmptyStateCard body="Loading M3U export state..." className={layoutClasses.emptyStateNarrow} title="Loading export" />;
  }

  if (playlistsQuery.isError || generatedRunsQuery.isError || profilesQuery.isError) {
    return (
      <EmptyStateCard
        body="M3U export data is unavailable right now."
        className={layoutClasses.emptyStateNarrow}
        title="Export unavailable"
        tone="error"
      />
    );
  }

  if (playlists.length === 0 && exportableGeneratedRuns.length === 0) {
    return (
      <EmptyStateCard
        body="Full-sync streaming playlists or generated runs are required before exporting M3U files."
        className={layoutClasses.emptyStateNarrow}
        title="No exportable playlists"
      />
    );
  }

  return (
    <form className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1" onSubmit={handlePreview}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className={textClasses.sectionTitle}>M3U export</h2>
          <p className={`mt-1 ${textClasses.bodyMuted}`}>
            {selectedExportTargetCount} {selectedExportTargetCount === 1 ? "export target" : "export targets"} selected.
          </p>
          <p className={`mt-1 max-w-2xl ${textClasses.bodyMuted}`}>
            Selected exports contain only the chosen playlists and generated runs. Full-library XML ignores this selection and includes every linked local track.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton disabled={exportRequest === null || previewMutation.isPending} type="submit">
            <Eye aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            {previewMutation.isPending ? "Previewing..." : "Preview"}
          </ActionButton>
          <ActionButton disabled={!isPreviewCurrent || exportMutation.isPending} onClick={handleExport} type="button">
            <FileDown aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            {exportMutation.isPending ? "Exporting..." : "Download ZIP"}
          </ActionButton>
          <ActionButton disabled={!isPreviewCurrent || rekordboxXmlMutation.isPending} onClick={handleRekordboxXmlExport} type="button">
            <FileDown aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            {rekordboxXmlMutation.isPending ? "Exporting..." : "Download selected XML"}
          </ActionButton>
          <ActionButton
            disabled={fullRekordboxXmlRequest === null || fullRekordboxXmlMutation.isPending}
            onClick={handleFullRekordboxXmlExport}
            type="button"
          >
            <FileDown aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            {fullRekordboxXmlMutation.isPending ? "Exporting..." : "Download full-library XML"}
          </ActionButton>
        </div>
      </div>

      {createProfileMutation.isError ? (
        <StatusMessage body="The export profile could not be saved." status="error" title="Profile save failed" />
      ) : null}
      {previewMutation.isError ? (
        <StatusMessage body="The export preview could not be generated." status="error" title="Preview failed" />
      ) : null}
      {exportMutation.isError ? (
        <StatusMessage body="The ZIP export could not be generated." status="error" title="Export failed" />
      ) : null}
      {rekordboxXmlMutation.isError ? (
        <StatusMessage body="The Rekordbox XML export could not be generated." status="error" title="XML export failed" />
      ) : null}
      {fullRekordboxXmlMutation.isError ? (
        <StatusMessage body="The full Rekordbox XML export could not be generated." status="error" title="Full XML export failed" />
      ) : null}
      {exportMutation.isSuccess ? <StatusMessage body="The ZIP download has started." status="success" title="Export ready" /> : null}
      {rekordboxXmlMutation.isSuccess ? (
        <StatusMessage body="The selected-target rekordbox.xml download has started." status="success" title="Selected XML export ready" />
      ) : null}
      {fullRekordboxXmlMutation.isSuccess ? (
        <StatusMessage body="The full-library rekordbox.xml download has started." status="success" title="Full-library XML export ready" />
      ) : null}

      <ExportProfileSelector
        libraryPath={libraryPath}
        onCreateProfile={handleCreateProfile}
        onLibraryPathChange={setLibraryPath}
        onProfileChange={handleProfileChange}
        profileName={profileName}
        profiles={profiles}
        selectedProfileId={selectedProfileId}
        setProfileName={setProfileName}
      />

      <ExportPathFormatSelector pathFormat={pathFormat} setPathFormat={setPathFormat} />

      <ExportFormatSelector selectedFormats={selectedFormats} setSelectedFormats={setSelectedFormats} />

      {isPreviewCurrent && previewMutation.data ? <ExportPreview preview={previewMutation.data} /> : null}

      {playlists.length > 0 ? (
        <PlaylistSelectionList
          playlists={playlists}
          searchQuery={searchQuery}
          selectedPlaylistIds={selectedPlaylistIds}
          setSearchQuery={setSearchQuery}
          setSelectedPlaylistIds={setSelectedPlaylistIds}
        />
      ) : null}

      <GeneratedRunSelectionList
        generatedRuns={exportableGeneratedRuns}
        selectedGeneratedRunIds={selectedGeneratedRunIds}
        setSelectedGeneratedRunIds={setSelectedGeneratedRunIds}
      />
    </form>
  );
}
