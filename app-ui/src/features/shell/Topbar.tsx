import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpenText, ListMusic, Sparkles, type LucideIcon } from "lucide-react";
import { ActionButton } from "../../components/ActionButton";
import { controlClasses, textClasses } from "../../styles/componentClasses";
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
      <p className="text-[12px] font-medium text-ctp-yellow" role="status">
        {pendingText}
      </p>
    );
  }

  if (isError) {
    return (
      <p className="text-[12px] font-medium text-ctp-red" role="alert">
        {errorText}
      </p>
    );
  }

  if (isSuccess) {
    return (
      <p className="text-[12px] font-medium text-ctp-green" role="status">
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
      <ActionButton key={actionLabel}>
        {actionLabel}
      </ActionButton>
    );
  }

  return (
    <header className="flex h-11 shrink-0 items-center justify-between border-b border-ctp-surface0 bg-ctp-mantle px-5">
      <div className="flex min-w-0 items-center gap-3">
        <span className={`h-8 w-8 shrink-0 ${controlClasses.iconFrame}`}>
          <TopbarIcon icon={view.icon} />
        </span>
        <div className="flex min-w-0 items-center gap-3">
          <h1 className={`truncate ${textClasses.title}`}>{view.title}</h1>
          <span
            className={`uppercase tracking-[0.14em] ${controlClasses.pill} ${getTopbarPillClasses(view.pillTone)}`}
          >
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
        {exportMutation.isSuccess ? <span className="text-[11px] font-medium text-ctp-green">M3U ready.</span> : null}
        {exportMutation.isError ? <span className="text-[11px] font-medium text-ctp-red">Export failed.</span> : null}
        {view.id !== playlistCollectionViewId ? (
          <ActionButton onClick={onConfigureSync}>
            Configure sync
          </ActionButton>
        ) : null}
        {view.actionLabels.map((actionLabel) => renderActionButton(actionLabel))}
      </div>
    </header>
  );
}
