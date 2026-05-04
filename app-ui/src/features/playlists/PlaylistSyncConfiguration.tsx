import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ActionButton } from "../../components/ActionButton";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { StatusMessage, type OperationStatus } from "../../components/StatusMessage";
import { surfaceClasses, textClasses } from "../../styles/componentClasses";
import { PlaylistActionStatus } from "../shell/Topbar";
import {
  playlistQueryKeys,
  refreshStreamingAccountMetadata,
  syncStreamingAccount,
  type StreamingPlaylistConfig,
  updateStreamingPlaylistConfig,
  useStreamingPlaylistConfigQuery,
} from "./queries";

type PlaylistCollectionStatus = "empty" | "error" | "loading" | "ready";

function formatPlaylistTimestamp(timestamp: string | null) {
  if (!timestamp) {
    return "Not synced yet";
  }

  return timestamp.replace("T", " ").replace(/(?:\.\d+)?Z?$/, "");
}

function getSelectedPlaylistCount(playlists: StreamingPlaylistConfig[]) {
  return playlists.filter((playlist) => playlist.selected_for_sync).length;
}

function PlaylistCollectionState({ status }: { status: PlaylistCollectionStatus }) {
  const copy = {
    empty: {
      title: "No selected playlists",
      body: "Configure which YouTube Music playlists to sync, then selected playlists will appear in the sidebar.",
    },
    error: {
      title: "Playlists unavailable",
      body: "The synced playlist list could not be loaded. Try again after the backend is reachable.",
    },
    loading: {
      title: "Loading playlists",
      body: "Checking for synced YouTube Music playlists.",
    },
    ready: {
      title: "Playlist sync configuration",
      body: "Review discovered YouTube Music playlists and choose which ones appear in the sync queue.",
    },
  } satisfies Record<PlaylistCollectionStatus, { body: string; title: string }>;

  return (
    <section className="flex min-h-0 flex-1 items-center justify-center">
      <EmptyStateCard body={copy[status].body} className="max-w-[420px] py-7" title={copy[status].title} />
    </section>
  );
}

function PlaylistSyncToggle({
  isPending,
  onToggle,
  playlist,
}: {
  isPending: boolean;
  onToggle: (selectedForSync: boolean) => void;
  playlist: StreamingPlaylistConfig;
}) {
  return (
    <label className="inline-flex shrink-0 items-center gap-2 text-[12px] font-semibold text-ctp-subtext0">
      <input
        aria-label={`Select ${playlist.title} for sync`}
        checked={playlist.selected_for_sync}
        className="h-4 w-4 rounded border-ctp-surface1 bg-ctp-surface0 text-ctp-mauve accent-ctp-mauve"
        disabled={isPending}
        onChange={(event) => onToggle(event.target.checked)}
        type="checkbox"
      />
      {isPending ? "Updating..." : playlist.selected_for_sync ? "Selected" : "Not selected"}
    </label>
  );
}

function PlaylistConfigRow({
  isTogglePending,
  onTogglePlaylist,
  playlist,
}: {
  isTogglePending: boolean;
  onTogglePlaylist: (playlist: StreamingPlaylistConfig, selectedForSync: boolean) => void;
  playlist: StreamingPlaylistConfig;
}) {
  return (
    <article className={`${surfaceClasses.panelRadius} border border-ctp-surface1/80 bg-ctp-mantle px-5 py-4`}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className={`truncate ${textClasses.title}`}>{playlist.title}</h3>
          <p className={`mt-1 ${textClasses.caption}`}>
            Provider ID {playlist.provider_playlist_id} / Account {playlist.account_id}
          </p>
        </div>
        <PlaylistSyncToggle
          isPending={isTogglePending}
          onToggle={(selectedForSync) => onTogglePlaylist(playlist, selectedForSync)}
          playlist={playlist}
        />
      </div>

      <dl className="mt-4 grid gap-3 text-[12px] sm:grid-cols-3">
        <div>
          <dt className="font-medium text-ctp-subtext0">Tracks</dt>
          <dd className="mt-1 font-semibold tabular-nums text-ctp-text">{playlist.track_count}</dd>
        </div>
        <div>
          <dt className="font-medium text-ctp-subtext0">Last metadata sync</dt>
          <dd className="mt-1 font-semibold text-ctp-text">{formatPlaylistTimestamp(playlist.synced_at)}</dd>
        </div>
        <div>
          <dt className="font-medium text-ctp-subtext0">Last sync error</dt>
          <dd className={playlist.last_sync_error ? "mt-1 font-semibold text-ctp-red" : "mt-1 font-semibold text-ctp-green"}>
            {playlist.last_sync_error ?? "None"}
          </dd>
        </div>
      </dl>
    </article>
  );
}

export function PlaylistSyncConfiguration() {
  const queryClient = useQueryClient();
  const configQuery = useStreamingPlaylistConfigQuery();
  const selectedSyncMutation = useMutation({
    mutationFn: syncStreamingAccount,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: playlistQueryKeys.list() }),
        queryClient.invalidateQueries({ queryKey: playlistQueryKeys.config() }),
      ]);
    },
  });
  const metadataRefreshMutation = useMutation({
    mutationFn: refreshStreamingAccountMetadata,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: playlistQueryKeys.list() }),
        queryClient.invalidateQueries({ queryKey: playlistQueryKeys.config() }),
      ]);
    },
  });
  const toggleMutation = useMutation({
    mutationFn: updateStreamingPlaylistConfig,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: playlistQueryKeys.list() }),
        queryClient.invalidateQueries({ queryKey: playlistQueryKeys.config() }),
      ]);
    },
  });
  const playlists = configQuery.data?.playlists ?? [];
  const selectedCount = getSelectedPlaylistCount(playlists);
  const accountId = playlists[0]?.account_id;
  const operationMessage = selectedSyncMutation.isPending
    ? {
        body: "Selected playlists are being synced. Sidebar counts and playlist views may update when the job finishes.",
        status: "pending",
        title: "Selected playlist sync in progress",
      }
    : selectedSyncMutation.isError
      ? {
          body: "The selected playlist sync request failed before a job could be queued.",
          status: "error",
          title: "Selected playlist sync failed",
        }
      : metadataRefreshMutation.isPending
        ? {
            body: "Playlist metadata is being refreshed. Newly discovered playlists may appear here after the job finishes.",
            status: "pending",
            title: "Metadata refresh in progress",
          }
        : metadataRefreshMutation.isError
          ? {
              body: "The playlist metadata refresh request failed before a job could be queued.",
              status: "error",
              title: "Metadata refresh failed",
            }
          : null;

  if (configQuery.isPending) {
    return <PlaylistCollectionState status="loading" />;
  }

  if (configQuery.isError) {
    return <PlaylistCollectionState status="error" />;
  }

  if (playlists.length === 0) {
    return <PlaylistCollectionState status="empty" />;
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className={textClasses.sectionTitle}>Playlist sync configuration</h2>
          <p className={`mt-1 ${textClasses.bodyMuted}`}>
            {selectedCount} of {playlists.length} discovered playlists selected for sync.
          </p>
        </div>
        <div className="flex flex-col items-start gap-2 sm:items-end">
          <div className="flex flex-wrap justify-start gap-2 sm:justify-end">
            <ActionButton
              disabled={accountId === undefined || selectedCount === 0 || selectedSyncMutation.isPending}
              onClick={() => {
                if (accountId !== undefined) {
                  selectedSyncMutation.mutate(accountId);
                }
              }}
            >
              {selectedSyncMutation.isPending ? "Syncing selected..." : "Sync selected"}
            </ActionButton>
            <ActionButton
              disabled={accountId === undefined || metadataRefreshMutation.isPending}
              onClick={() => {
                if (accountId !== undefined) {
                  metadataRefreshMutation.mutate(accountId);
                }
              }}
            >
              {metadataRefreshMutation.isPending ? "Refreshing..." : "Refresh playlist metadata"}
            </ActionButton>
          </div>
          <PlaylistActionStatus
            errorText="Selected playlist sync failed."
            isError={selectedSyncMutation.isError}
            isPending={selectedSyncMutation.isPending}
            isSuccess={selectedSyncMutation.isSuccess}
            pendingText="Syncing selected playlists..."
            successText="Selected playlist sync queued."
          />
          <PlaylistActionStatus
            errorText="Metadata refresh failed."
            isError={metadataRefreshMutation.isError}
            isPending={metadataRefreshMutation.isPending}
            isSuccess={metadataRefreshMutation.isSuccess}
            pendingText="Refreshing playlist metadata..."
            successText="Metadata refresh queued."
          />
        </div>
      </div>

      <div aria-label="Playlist sync configuration list" className="min-h-0 flex-1 overflow-y-auto pb-1 pr-1" role="region">
        <div className="space-y-3">
          {operationMessage ? (
            <StatusMessage
              body={operationMessage.body}
              status={operationMessage.status as OperationStatus}
              title={operationMessage.title}
            />
          ) : null}
          {playlists.map((playlist) => (
            <PlaylistConfigRow
              isTogglePending={toggleMutation.isPending && toggleMutation.variables?.playlistId === playlist.id}
              key={playlist.id}
              onTogglePlaylist={(playlistToUpdate, selectedForSync) =>
                toggleMutation.mutate({
                  playlistId: playlistToUpdate.id,
                  selected_for_sync: selectedForSync,
                })
              }
              playlist={playlist}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
