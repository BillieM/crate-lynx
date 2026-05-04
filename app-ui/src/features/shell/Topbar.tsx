import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpenText, ListMusic, Sparkles, type LucideIcon } from "lucide-react";
import { ActionButton } from "../../components/ActionButton";
import { controlClasses, shellClasses, textClasses } from "../../styles/componentClasses";
import {
  exportPlaylistM3u,
  syncStreamingPlaylist,
  usePlaylistDetailQuery,
} from "../playlists/queries";
import { pillToneClasses, type PillTone } from "../../styles/toneClasses";
import type { PlaylistSyncViewState, TopbarPillTone, ViewConfig } from "./types";

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

function getTopbarPillClasses(tone: TopbarPillTone) {
  const toneMap = {
    "pill-info": "neutral",
    "pill-lib": "accent",
    "pill-pending": "pending",
  } satisfies Record<TopbarPillTone, PillTone>;

  return pillToneClasses[toneMap[tone]];
}

function TopbarIcon({ icon }: { icon: ViewConfig["icon"] }) {
  const Icon = topbarIconMap[icon];

  return <Icon aria-hidden="true" className="h-4 w-4" strokeWidth={1.7} />;
}

const topbarIconMap = {
  library: BookOpenText,
  playlist: ListMusic,
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
  onConfigureSync,
  onPlaylistSyncStateChange,
  playlistCollectionViewId,
  view,
}: {
  onConfigureSync: () => void;
  onPlaylistSyncStateChange: (state: PlaylistSyncViewState) => void;
  playlistCollectionViewId: string;
  view: ViewConfig;
}) {
  const queryClient = useQueryClient();
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
      await queryClient.invalidateQueries({ queryKey: ["playlists"] });
      if (view.playlistResourceId !== undefined) {
        await queryClient.invalidateQueries({ queryKey: ["playlists", view.playlistResourceId] });
      }
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
      <div className="flex min-w-0 items-center gap-2.5">
        <span className={`${shellClasses.topbarIcon} shrink-0 ${controlClasses.iconFrame}`}>
          <TopbarIcon icon={view.icon} />
        </span>
        <div className="flex min-w-0 items-center gap-2.5">
          <h1 className={`truncate ${textClasses.title}`}>{view.title}</h1>
          <span className={`${textClasses.pillEyebrow} ${controlClasses.pill} ${getTopbarPillClasses(view.pillTone)}`}>
            {view.pillLabel}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2">
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
        {view.id !== playlistCollectionViewId ? (
          <ActionButton className={controlClasses.actionButtonCompact} onClick={onConfigureSync}>
            Configure sync
          </ActionButton>
        ) : null}
        {view.actionLabels.map((actionLabel) => renderActionButton(actionLabel))}
      </div>
    </header>
  );
}
