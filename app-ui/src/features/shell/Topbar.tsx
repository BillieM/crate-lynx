import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, BookOpenText, FileDown, ListMusic, RefreshCw, Settings, Sparkles, type LucideIcon } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { IconButton } from "../../components/IconButton";
import { useDelayedInvalidate } from "../../lib/useDelayedInvalidate";
import { controlClasses, shellClasses, textClasses } from "../../styles/componentClasses";
import {
  invalidatePlaylistContentQueries,
  syncStreamingPlaylist,
  usePlaylistDetailQuery,
} from "../playlists/queries";
import { streamingAccountPlaylistSyncJobInvalidationKeys } from "../streamingAccounts/queries";
import type { PlaylistSyncViewState, ViewConfig } from "./types";

function TopbarIcon({ icon }: { icon: ViewConfig["icon"] }) {
  const Icon = topbarIconMap[icon];

  return <Icon aria-hidden="true" className="h-4 w-4" strokeWidth={1.7} />;
}

const topbarIconMap = {
  library: BookOpenText,
  playlist: ListMusic,
  settings: Settings,
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
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const delayedInvalidate = useDelayedInvalidate();
  const playlistDetailQuery = usePlaylistDetailQuery(view.playlistResourceId ?? null);
  const playlist = playlistDetailQuery.data?.playlist;
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

  function renderToolbarAction(actionLabel: string) {
    if (actionLabel === "Sync") {
      if (view.playlistResourceId === undefined) {
        return null;
      }

      const canSync = playlist !== undefined && !syncMutation.isPending;
      const label = syncMutation.isPending ? "Syncing playlist" : "Sync";

      return (
        <IconButton
          aria-live="polite"
          disabled={!canSync}
          key={actionLabel}
          label={label}
          onClick={() => {
            if (view.playlistResourceId !== undefined) {
              syncMutation.mutate(view.playlistResourceId);
            }
          }}
          tooltip={label}
        >
          <RefreshCw
            aria-hidden="true"
            className={syncMutation.isPending ? "animate-spin" : undefined}
            focusable="false"
            strokeWidth={1.8}
          />
        </IconButton>
      );
    }

    if (actionLabel === "Export M3U") {
      const canExport = view.playlistResourceId !== undefined;
      const label = "Export M3U";

      return (
        <IconButton
          disabled={!canExport}
          key={actionLabel}
          label={label}
          onClick={() => {
            if (view.playlistResourceId !== undefined) {
              navigate(`/playlists/export?playlist=${view.playlistResourceId}`);
            }
          }}
          tooltip={label}
        >
          <FileDown aria-hidden="true" focusable="false" strokeWidth={1.8} />
        </IconButton>
      );
    }

    return null;
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
        <div aria-label="Topbar actions" className="flex items-center gap-1.5" role="toolbar">
          {view.actionLabels.map((actionLabel) => renderToolbarAction(actionLabel))}
          <IconButton
            label={isSettingsView ? "Return to Link proposals" : "Open app settings"}
            onClick={isSettingsView ? onNavigateHome : onOpenAppSettings}
          >
            {isSettingsView ? (
              <ArrowLeft aria-hidden="true" focusable="false" strokeWidth={1.8} />
            ) : (
              <Settings aria-hidden="true" focusable="false" strokeWidth={1.8} />
            )}
          </IconButton>
        </div>
      </div>
    </header>
  );
}
