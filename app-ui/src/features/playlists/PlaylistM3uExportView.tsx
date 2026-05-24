import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Eye, FileDown, FileText, Folder, Music2, Plus, Search } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ActionButton } from "../../components/ActionButton";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { StatusMessage } from "../../components/StatusMessage";
import { controlClasses, layoutClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import { type GeneratedPlaylist, useGeneratedPlaylistsQuery } from "../sonic/queries";
import {
  createM3uExportProfile,
  exportM3uZip,
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
const emptyGeneratedPlaylists: GeneratedPlaylist[] = [];
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
  generatedPlaylistIds,
  libraryPath,
  pathFormat,
  playlistIds,
  selectedProfileId,
}: {
  formats: M3uExportFormat[];
  generatedPlaylistIds: number[];
  libraryPath: string;
  pathFormat: M3uExportPathFormat;
  playlistIds: number[];
  selectedProfileId: number | null;
}): M3uExportRequest | null {
  if ((playlistIds.length === 0 && generatedPlaylistIds.length === 0) || formats.length === 0) {
    return null;
  }

  if (selectedProfileId !== null) {
    const request: M3uExportRequest = {
      formats,
      path_format: pathFormat,
      playlist_ids: playlistIds,
      profile_id: selectedProfileId,
    };
    if (generatedPlaylistIds.length > 0) {
      request.generated_playlist_ids = generatedPlaylistIds;
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
  if (generatedPlaylistIds.length > 0) {
    request.generated_playlist_ids = generatedPlaylistIds;
  }
  return request;
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
    <section className="grid min-h-0 gap-3" aria-label="Playlist export selection">
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

      <div className="min-h-0 overflow-y-auto pr-1">
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

function GeneratedPlaylistSelectionList({
  generatedPlaylists,
  selectedGeneratedPlaylistIds,
  setSelectedGeneratedPlaylistIds,
}: {
  generatedPlaylists: GeneratedPlaylist[];
  selectedGeneratedPlaylistIds: Set<number>;
  setSelectedGeneratedPlaylistIds: (playlistIds: Set<number>) => void;
}) {
  const selectedCount = generatedPlaylists.filter((playlist) => selectedGeneratedPlaylistIds.has(playlist.id)).length;

  function togglePlaylist(playlistId: number) {
    const nextSelection = new Set(selectedGeneratedPlaylistIds);
    if (nextSelection.has(playlistId)) {
      nextSelection.delete(playlistId);
    } else {
      nextSelection.add(playlistId);
    }
    setSelectedGeneratedPlaylistIds(nextSelection);
  }

  if (generatedPlaylists.length === 0) {
    return null;
  }

  return (
    <section className="grid min-h-0 gap-3" aria-label="Generated playlist export selection">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className={textClasses.sectionTitle}>Generated playlists</h2>
          <p className={`mt-1 ${textClasses.bodyMuted}`}>
            {selectedCount} of {generatedPlaylists.length} selected
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            className={controlClasses.actionButtonCompact}
            onClick={() => setSelectedGeneratedPlaylistIds(new Set(generatedPlaylists.map((playlist) => playlist.id)))}
            type="button"
          >
            All
          </ActionButton>
          <ActionButton className={controlClasses.actionButtonCompact} onClick={() => setSelectedGeneratedPlaylistIds(new Set())} type="button">
            None
          </ActionButton>
        </div>
      </div>

      <div className="grid gap-2.5 md:grid-cols-2">
        {generatedPlaylists.map((playlist) => {
          const isSelected = selectedGeneratedPlaylistIds.has(playlist.id);

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
                  <span className={`block truncate ${textClasses.title}`}>{playlist.name}</span>
                  <span className={`mt-1 block ${textClasses.caption}`}>
                    Run #{playlist.run_id} · {playlist.track_count.toLocaleString()} tracks
                  </span>
                </span>
              </span>
            </button>
          );
        })}
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
              {playlist.filenames.join(" + ")}
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
  const generatedPlaylistsQuery = useGeneratedPlaylistsQuery();
  const profilesQuery = useM3uExportProfilesQuery();
  const playlists = playlistsQuery.data?.playlists ?? emptyPlaylists;
  const generatedPlaylists = generatedPlaylistsQuery.data?.playlists ?? emptyGeneratedPlaylists;
  const profiles = profilesQuery.data?.profiles ?? emptyProfiles;
  const [selectedProfileId, setSelectedProfileId] = useState<number | null>(null);
  const [libraryPath, setLibraryPath] = useState("");
  const [profileName, setProfileName] = useState("Default export");
  const [searchQuery, setSearchQuery] = useState("");
  const [pathFormat, setPathFormat] = useState<M3uExportPathFormat>("file_url");
  const [selectedFormats, setSelectedFormats] = useState<Set<M3uExportFormat>>(
    new Set(exportFormatOptions.map((option) => option.value)),
  );
  const [selectedPlaylistIds, setSelectedPlaylistIds] = useState<Set<number>>(new Set());
  const [selectedGeneratedPlaylistIds, setSelectedGeneratedPlaylistIds] = useState<Set<number>>(new Set());
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
  const selectedGeneratedPlaylistIdList = useMemo(
    () => generatedPlaylists.filter((playlist) => selectedGeneratedPlaylistIds.has(playlist.id)).map((playlist) => playlist.id),
    [generatedPlaylists, selectedGeneratedPlaylistIds],
  );
  const exportRequest = useMemo(
    () =>
      buildExportRequest({
        formats: selectedFormatList,
        generatedPlaylistIds: selectedGeneratedPlaylistIdList,
        libraryPath,
        pathFormat,
        playlistIds: selectedPlaylistIdList,
        selectedProfileId,
      }),
    [
      libraryPath,
      pathFormat,
      selectedFormatList,
      selectedGeneratedPlaylistIdList,
      selectedPlaylistIdList,
      selectedProfileId,
    ],
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
  }, [profiles, selectedProfileId]);

  useEffect(() => {
    if (hasSeededSelection || playlistsQuery.isPending || generatedPlaylistsQuery.isPending) {
      return;
    }

    const requestedGeneratedPlaylistId = Number(searchParams.get("generated_playlist"));
    const requestedGeneratedPlaylist = generatedPlaylists.find((playlist) => playlist.id === requestedGeneratedPlaylistId);
    const requestedPlaylistId = Number(searchParams.get("playlist"));
    const requestedPlaylist = playlists.find((playlist) => playlist.id === requestedPlaylistId);
    if (requestedGeneratedPlaylist) {
      setSelectedPlaylistIds(new Set());
      setSelectedGeneratedPlaylistIds(new Set([requestedGeneratedPlaylist.id]));
    } else {
      setSelectedPlaylistIds(
        new Set(requestedPlaylist ? [requestedPlaylist.id] : playlists.map((playlist) => playlist.id)),
      );
      setSelectedGeneratedPlaylistIds(new Set());
    }
    setHasSeededSelection(true);
  }, [
    generatedPlaylists,
    generatedPlaylistsQuery.isPending,
    hasSeededSelection,
    playlists,
    playlistsQuery.isPending,
    searchParams,
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

  if (playlistsQuery.isPending || generatedPlaylistsQuery.isPending || profilesQuery.isPending) {
    return <EmptyStateCard body="Loading M3U export state..." className={layoutClasses.emptyStateNarrow} title="Loading export" />;
  }

  if (playlistsQuery.isError || generatedPlaylistsQuery.isError || profilesQuery.isError) {
    return (
      <EmptyStateCard
        body="M3U export data is unavailable right now."
        className={layoutClasses.emptyStateNarrow}
        title="Export unavailable"
        tone="error"
      />
    );
  }

  if (playlists.length === 0 && generatedPlaylists.length === 0) {
    return (
      <EmptyStateCard
        body="Exportable streaming or generated playlists are required before exporting M3U files."
        className={layoutClasses.emptyStateNarrow}
        title="No exportable playlists"
      />
    );
  }

  return (
    <form className="flex min-h-0 flex-1 flex-col gap-4" onSubmit={handlePreview}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className={textClasses.sectionTitle}>M3U export</h2>
          <p className={`mt-1 ${textClasses.bodyMuted}`}>
            {selectedPlaylistIdList.length + selectedGeneratedPlaylistIdList.length}{" "}
            {selectedPlaylistIdList.length + selectedGeneratedPlaylistIdList.length === 1 ? "playlist" : "playlists"} selected.
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
      {exportMutation.isSuccess ? <StatusMessage body="The ZIP download has started." status="success" title="Export ready" /> : null}

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

      <PlaylistSelectionList
        playlists={playlists}
        searchQuery={searchQuery}
        selectedPlaylistIds={selectedPlaylistIds}
        setSearchQuery={setSearchQuery}
        setSelectedPlaylistIds={setSelectedPlaylistIds}
      />

      <GeneratedPlaylistSelectionList
        generatedPlaylists={generatedPlaylists}
        selectedGeneratedPlaylistIds={selectedGeneratedPlaylistIds}
        setSelectedGeneratedPlaylistIds={setSelectedGeneratedPlaylistIds}
      />
    </form>
  );
}
