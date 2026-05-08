import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, BookOpenText, Cog, ListMusic, Sparkles, type LucideIcon } from "lucide-react";
import { ActionButton } from "../../components/ActionButton";
import { useDelayedInvalidate } from "../../lib/useDelayedInvalidate";
import { controlClasses, shellClasses, textClasses } from "../../styles/componentClasses";
import {
  exportPlaylistM3u,
  invalidatePlaylistContentQueries,
  syncStreamingPlaylist,
  usePlaylistDetailQuery,
} from "../playlists/queries";
import { streamingAccountPlaylistSyncJobInvalidationKeys } from "../streamingAccounts/queries";
import type { PlaylistSyncViewState, ViewConfig } from "./types";

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

function TopbarIcon({ icon }: { icon: ViewConfig["icon"] }) {
  const Icon = topbarIconMap[icon];

  return <Icon aria-hidden="true" className="h-4 w-4" strokeWidth={1.7} />;
}

const topbarIconMap = {
  library: BookOpenText,
  playlist: ListMusic,
  settings: Cog,
  spark: Sparkles,
} satisfies Record<ViewConfig["icon"], LucideIcon>;

export function PlaylistActionStatus({
  errorText,
  isError,
  isPending,
  isSuccess,
  pendingText,
  successText,
}: {
  errorText: string;
  isError: boolean;
  isPending: boolean;
  isSuccess: boolean;
  pendingText: string;
  successText: string;
}) {
  if (isPending) {
    return (
      <p className={`${textClasses.status} text-ctp-yellow`} role="status">
        {pendingText}
      </p>
    );
  }

  if (isError) {
    return (
      <p className={`${textClasses.status} text-ctp-red`} role="alert">
        {errorText}
      </p>
    );
  }

  if (isSuccess) {
    return (
      <p className={`${textClasses.status} text-ctp-green`} role="status">
        {successText}
      </p>
    );
  }

  return null;
}

export function Topbar({
  isSettingsView,
  onNavigateHome,
  onPlaylistSyncStateChange,
  onOpenAppSettings,
  view,
}: {
  isSettingsView: boolean;
  onNavigateHome: () => void;
  onOpenAppSettings: () => void;
  onPlaylistSyncStateChange: (state: PlaylistSyncViewState) => void;
  view: ViewConfig;
}) {
  const queryClient = useQueryClient();
  const delayedInvalidate = useDelayedInvalidate();
  const playlistDetailQuery = usePlaylistDetailQuery(view.playlistResourceId ?? null);
  const playlist = playlistDetailQuery.data?.playlist;
  const exportMutation = useMutation({
    mutationFn: exportPlaylistM3u,
    onSuccess: ({ blob, filename }) => {
      downloadBlob(blob, filename);
    },
  });
  const syncMutation = useMutation({
    mutationFn: syncStreamingPlaylist,
    onMutate: (playlistId) => {
      onPlaylistSyncStateChange({ playlistId: Number(playlistId), status: "pending" });
    },
    onError: (_error, playlistId) => {
      onPlaylistSyncStateChange({ playlistId: Number(playlistId), status: "error" });
    },
    onSuccess: async (_data, playlistId) => {
      onPlaylistSyncStateChange({ playlistId: Number(playlistId), status: "success" });
      await invalidatePlaylistContentQueries(queryClient, [playlistId]);
      delayedInvalidate(streamingAccountPlaylistSyncJobInvalidationKeys([playlistId]));
    },
  });

  function renderActionButton(actionLabel: string) {
    if (actionLabel === "Sync") {
      if (view.playlistResourceId === undefined) {
        return null;
      }

      const canSync = playlist !== undefined && !syncMutation.isPending;

      return (
        <ActionButton
          aria-live="polite"
          className={controlClasses.actionButtonCompact}
          disabled={!canSync}
          key={actionLabel}
          onClick={() => {
            if (view.playlistResourceId !== undefined) {
              syncMutation.mutate(view.playlistResourceId);
            }
          }}
        >
          {syncMutation.isPending ? "Syncing..." : actionLabel}
        </ActionButton>
      );
    }

    if (actionLabel === "Export M3U") {
      const canExport = view.playlistResourceId !== undefined && !exportMutation.isPending;

      return (
        <ActionButton
          aria-live="polite"
          className={controlClasses.actionButtonCompact}
          disabled={!canExport}
          key={actionLabel}
          onClick={() => {
            if (view.playlistResourceId !== undefined) {
              exportMutation.mutate(view.playlistResourceId);
            }
          }}
        >
          {exportMutation.isPending ? "Exporting..." : actionLabel}
        </ActionButton>
      );
    }

    return (
      <ActionButton className={controlClasses.actionButtonCompact} key={actionLabel}>
        {actionLabel}
      </ActionButton>
    );
  }

  return (
    <header className={shellClasses.topbar}>
      <div className="flex min-w-0 flex-1 items-center gap-2.5 max-md:w-full">
        <span className={`${shellClasses.topbarIcon} shrink-0 ${controlClasses.iconFrame}`}>
          <TopbarIcon icon={view.icon} />
        </span>
        <h1 className={`min-w-0 flex-1 truncate ${textClasses.title}`}>{view.title}</h1>
      </div>

      <div className="flex min-w-0 flex-wrap items-center justify-end gap-2 max-md:w-full max-md:justify-start">
        <PlaylistActionStatus
          errorText="Playlist sync failed."
          isError={syncMutation.isError}
          isPending={syncMutation.isPending}
          isSuccess={syncMutation.isSuccess}
          pendingText="Syncing playlist..."
          successText="Playlist sync queued."
        />
        {exportMutation.isSuccess ? <span className={`${textClasses.finePrint} font-medium text-ctp-green`}>M3U ready.</span> : null}
        {exportMutation.isError ? <span className={`${textClasses.finePrint} font-medium text-ctp-red`}>Export failed.</span> : null}
        <ActionButton
          aria-label={isSettingsView ? "Return to Link proposals" : "Open app settings"}
          className="inline-flex h-7 w-7 shrink-0 items-center justify-center p-0 text-ctp-text [&_svg]:block [&_svg]:h-4 [&_svg]:w-4"
          onClick={isSettingsView ? onNavigateHome : onOpenAppSettings}
        >
          {isSettingsView ? (
            <ArrowLeft aria-hidden="true" focusable="false" strokeWidth={1.8} />
          ) : (
            <Cog aria-hidden="true" focusable="false" strokeWidth={1.8} />
          )}
        </ActionButton>
        {view.actionLabels.map((actionLabel) => renderActionButton(actionLabel))}
      </div>
    </header>
  );
}
