import { createColumnHelper, type RowSelectionState, type SortingState } from "@tanstack/react-table";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, RefreshCw, Settings2, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { ActionButton } from "../../components/ActionButton";
import { DataTable } from "../../components/DataTable";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { StatusMessage, type OperationStatus } from "../../components/StatusMessage";
import { useDelayedInvalidate } from "../../lib/useDelayedInvalidate";
import { controlClasses, layoutClasses, textClasses } from "../../styles/componentClasses";
import { actionButtonToneClasses } from "../../styles/toneClasses";
import { maintenanceQueryKeys } from "../maintenance/queries";
import { PlaylistActionStatus } from "../shell/Topbar";
import { streamingAccountQueryKeys, useStreamingAccountsQuery } from "../streamingAccounts/queries";
import {
  playlistQueryKeys,
  refreshStreamingAccountMetadata,
  syncStreamingAccount,
  syncStreamingPlaylist,
  type StreamingPlaylistConfig,
  updateStreamingPlaylistConfig,
  useStreamingPlaylistConfigQuery,
} from "./queries";

type PlaylistCollectionStatus = "empty" | "error" | "loading" | "ready";
const emptyPlaylistConfigs: StreamingPlaylistConfig[] = [];

function formatPlaylistTimestamp(timestamp: string | null) {
  if (!timestamp) {
    return "Not synced yet";
  }

  return timestamp.replace("T", " ").replace(/(?:\.\d+)?Z?$/, "");
}

function getSelectedPlaylistCount(playlists: StreamingPlaylistConfig[]) {
  return playlists.filter((playlist) => playlist.selected_for_sync).length;
}

const columnHelper = createColumnHelper<StreamingPlaylistConfig>();

type BulkPlaylistConfigStatus = {
  body: string;
  status: "error" | "success";
  title: string;
};

async function settleInChunks<TItem, TResult>(
  items: TItem[],
  chunkSize: number,
  worker: (item: TItem) => Promise<TResult>,
): Promise<PromiseSettledResult<TResult>[]> {
  const settledResults: PromiseSettledResult<TResult>[] = [];

  for (let index = 0; index < items.length; index += chunkSize) {
    settledResults.push(...(await Promise.allSettled(items.slice(index, index + chunkSize).map(worker))));
  }

  return settledResults;
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
      <div className="grid justify-items-center gap-3">
        <EmptyStateCard body={copy[status].body} className={layoutClasses.emptyStateNarrow} title={copy[status].title} />
        {status === "empty" ? (
          <a
            className={`${controlClasses.actionButton} ${actionButtonToneClasses.neutral}`}
            href="/settings/authentication"
          >
            Authentication
          </a>
        ) : null}
      </div>
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
    <label className={`inline-flex shrink-0 items-center gap-2 font-semibold text-ctp-subtext0 ${textClasses.status}`}>
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

export function PlaylistSyncConfiguration() {
  const queryClient = useQueryClient();
  const delayedInvalidate = useDelayedInvalidate();
  const configQuery = useStreamingPlaylistConfigQuery();
  const accountsQuery = useStreamingAccountsQuery();
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [sorting, setSorting] = useState<SortingState>([]);
  const [bulkStatus, setBulkStatus] = useState<BulkPlaylistConfigStatus | null>(null);
  const [isBulkUpdating, setIsBulkUpdating] = useState(false);
  const [isBulkSyncingRows, setIsBulkSyncingRows] = useState(false);
  const selectedSyncMutation = useMutation({
    mutationFn: syncStreamingAccount,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: playlistQueryKeys.list() }),
        queryClient.invalidateQueries({ queryKey: playlistQueryKeys.config() }),
      ]);
      scheduleStreamingSyncRefresh();
    },
  });
  const metadataRefreshMutation = useMutation({
    mutationFn: refreshStreamingAccountMetadata,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: playlistQueryKeys.list() }),
        queryClient.invalidateQueries({ queryKey: playlistQueryKeys.config() }),
      ]);
      scheduleStreamingSyncRefresh();
    },
  });
  const toggleMutation = useMutation({
    mutationFn: updateStreamingPlaylistConfig,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: playlistQueryKeys.list() }),
        queryClient.invalidateQueries({ queryKey: playlistQueryKeys.config() }),
        queryClient.invalidateQueries({ queryKey: maintenanceQueryKeys.missingLocally() }),
      ]);
    },
  });
  const playlists = configQuery.data?.playlists ?? emptyPlaylistConfigs;
  const selectedCount = getSelectedPlaylistCount(playlists);
  const accountId = playlists[0]?.account_id;
  const accounts = accountsQuery.data?.accounts ?? [];
  const activeAccount =
    accounts.find((account) => account.id === accountId) ??
    accounts.find((account) => account.provider === "youtube_music") ??
    null;
  const accountAuthError =
    activeAccount && (activeAccount.auth_state === "error" || activeAccount.auth_error !== null)
      ? {
          body: activeAccount.auth_error_at
            ? `${activeAccount.auth_error ?? "Authentication needs attention."} Reported ${formatPlaylistTimestamp(activeAccount.auth_error_at)}.`
            : (activeAccount.auth_error ?? "Authentication needs attention before sync can run."),
          title: "YouTube Music authentication needs attention",
        }
      : null;
  const hasAccountAuthError = accountAuthError !== null;
  const selectedRows = useMemo(
    () => playlists.filter((playlist) => rowSelection[String(playlist.id)]),
    [playlists, rowSelection],
  );
  const operationMessage = selectedSyncMutation.isPending
    ? {
        body: "Enabled playlists are being synced. Sidebar counts and playlist views may update when the job finishes.",
        status: "pending",
        title: "Enabled playlist sync in progress",
      }
    : selectedSyncMutation.isError
      ? {
          body: "The enabled playlist sync request failed before a job could be queued.",
          status: "error",
          title: "Enabled playlist sync failed",
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
  const columns = useMemo(
    () => [
      columnHelper.accessor("title", {
        cell: (info) => <span className="block max-w-[18rem] truncate font-semibold">{info.getValue()}</span>,
        header: "Playlist",
        meta: {
          widthClass: "min-w-[13rem]",
        },
      }),
      columnHelper.display({
        cell: (info) => (
          <PlaylistSyncToggle
            isPending={toggleMutation.isPending && toggleMutation.variables?.playlistId === info.row.original.id}
            onToggle={(selectedForSync) =>
              toggleMutation.mutate({
                playlistId: info.row.original.id,
                selected_for_sync: selectedForSync,
              })
            }
            playlist={info.row.original}
          />
        ),
        header: "Sync enabled",
        meta: {
          widthClass: "min-w-[10rem]",
        },
      }),
      columnHelper.accessor("track_count", {
        cell: (info) => <span className="tabular-nums">{info.getValue().toLocaleString()}</span>,
        header: "Tracks",
        meta: {
          align: "end",
          widthClass: "w-24",
        },
      }),
      columnHelper.accessor("synced_at", {
        cell: (info) => <span className="block max-w-[12rem] truncate">{formatPlaylistTimestamp(info.getValue())}</span>,
        header: "Last metadata sync",
        meta: {
          hideBelow: "md",
          widthClass: "min-w-[12rem]",
        },
      }),
      columnHelper.accessor("last_sync_error", {
        cell: (info) => {
          const lastSyncError = info.getValue();

          return (
            <span
              className={`block max-w-[14rem] truncate font-semibold ${lastSyncError ? "text-ctp-red" : "text-ctp-green"}`}
              title={lastSyncError ?? "None"}
            >
              {lastSyncError ?? "None"}
            </span>
          );
        },
        header: "Last sync error",
        meta: {
          hideBelow: "lg",
          widthClass: "min-w-[11rem]",
        },
      }),
      columnHelper.accessor("provider_playlist_id", {
        cell: (info) => <span className="block max-w-[12rem] truncate font-mono text-[11px]">{info.getValue()}</span>,
        header: "Provider ID",
        meta: {
          hideBelow: "lg",
          widthClass: "min-w-[10rem]",
        },
      }),
      columnHelper.accessor("account_id", {
        cell: (info) => <span className="tabular-nums">{info.getValue()}</span>,
        header: "Account",
        meta: {
          align: "end",
          hideBelow: "md",
          widthClass: "w-24",
        },
      }),
      columnHelper.display({
        cell: (info) => (
          <ActionButton
            className="inline-flex items-center gap-1.5 whitespace-nowrap"
            disabled={isBulkUpdating || toggleMutation.isPending}
            onClick={() =>
              toggleMutation.mutate({
                playlistId: info.row.original.id,
                selected_for_sync: !info.row.original.selected_for_sync,
              })
            }
          >
            {info.row.original.selected_for_sync ? (
              <XCircle aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            ) : (
              <CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            )}
            {info.row.original.selected_for_sync ? "Disable" : "Enable"}
          </ActionButton>
        ),
        enableSorting: false,
        header: "Actions",
        meta: {
          widthClass: "w-32",
        },
      }),
    ],
    [isBulkUpdating, toggleMutation],
  );

  async function refreshPlaylistQueries() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: playlistQueryKeys.list() }),
      queryClient.invalidateQueries({ queryKey: playlistQueryKeys.config() }),
      queryClient.invalidateQueries({ queryKey: maintenanceQueryKeys.missingLocally() }),
    ]);
  }

  function scheduleStreamingSyncRefresh() {
    delayedInvalidate([
      playlistQueryKeys.list(),
      playlistQueryKeys.config(),
      streamingAccountQueryKeys.list(),
    ]);
  }

  async function handleBulkSelectionUpdate(selectedForSync: boolean) {
    if (selectedRows.length === 0 || isBulkUpdating) {
      return;
    }

    setIsBulkUpdating(true);
    setBulkStatus(null);

    const results = await settleInChunks(selectedRows, 5, (playlist) =>
      updateStreamingPlaylistConfig({
        playlistId: playlist.id,
        selected_for_sync: selectedForSync,
      }),
    );
    const successCount = results.filter((result) => result.status === "fulfilled").length;
    const failureCount = results.filter((result) => result.status === "rejected").length;
    const actionLabel = selectedForSync ? "enabled" : "disabled";

    await refreshPlaylistQueries();

    setRowSelection({});
    setIsBulkUpdating(false);
    setBulkStatus({
      body:
        failureCount > 0
          ? `${successCount} ${successCount === 1 ? "playlist was" : "playlists were"} ${actionLabel} and ${failureCount} ${failureCount === 1 ? "playlist failed" : "playlists failed"}.`
          : `${successCount} ${successCount === 1 ? "playlist was" : "playlists were"} ${actionLabel}.`,
      status: failureCount > 0 ? "error" : "success",
      title: failureCount > 0 ? "Playlist update partially failed" : `Playlist sync ${actionLabel}`,
    });
  }

  async function handleBulkRowSync() {
    if (selectedRows.length === 0 || isBulkSyncingRows) {
      return;
    }

    setIsBulkSyncingRows(true);
    setBulkStatus(null);

    const results = await settleInChunks(selectedRows, 5, (playlist) => syncStreamingPlaylist(playlist.id));
    const successCount = results.filter((result) => result.status === "fulfilled").length;
    const failureCount = results.filter((result) => result.status === "rejected").length;

    await refreshPlaylistQueries();
    scheduleStreamingSyncRefresh();

    setRowSelection({});
    setIsBulkSyncingRows(false);
    setBulkStatus({
      body:
        failureCount > 0
          ? `${successCount} ${successCount === 1 ? "playlist was" : "playlists were"} queued and ${failureCount} ${failureCount === 1 ? "playlist failed" : "playlists failed"}.`
          : `${successCount} ${successCount === 1 ? "playlist was" : "playlists were"} queued for sync.`,
      status: failureCount > 0 ? "error" : "success",
      title: failureCount > 0 ? "Playlist sync partially failed" : "Playlist sync queued",
    });
  }

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
              disabled={hasAccountAuthError || accountId === undefined || selectedCount === 0 || selectedSyncMutation.isPending}
              onClick={() => {
                if (accountId !== undefined) {
                  selectedSyncMutation.mutate(accountId);
                }
              }}
            >
              {selectedSyncMutation.isPending ? "Syncing enabled..." : "Sync enabled"}
            </ActionButton>
            <ActionButton
              disabled={hasAccountAuthError || accountId === undefined || metadataRefreshMutation.isPending}
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
            errorText="Enabled playlist sync failed."
            isError={selectedSyncMutation.isError}
            isPending={selectedSyncMutation.isPending}
            isSuccess={selectedSyncMutation.isSuccess}
            pendingText="Syncing enabled playlists..."
            successText="Enabled playlist sync queued."
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
          {accountAuthError ? (
            <div className="grid gap-2">
              <StatusMessage body={accountAuthError.body} status="error" title={accountAuthError.title} />
              <a
                className={`${controlClasses.actionButton} ${actionButtonToneClasses.danger} w-fit`}
                href="/settings/authentication"
              >
                Refresh authentication
              </a>
            </div>
          ) : null}
          {bulkStatus ? <StatusMessage body={bulkStatus.body} status={bulkStatus.status} title={bulkStatus.title} /> : null}
          <div className="grid gap-2.5">
            <div className="flex items-center justify-between gap-3 px-1">
              <div className="flex items-center gap-2 text-ctp-subtext0">
                <Settings2 aria-hidden="true" className="h-4 w-4" strokeWidth={1.8} />
                <h3 className={textClasses.label}>Discovered playlist rows</h3>
              </div>
              <p className={`${textClasses.caption} tabular-nums`}>{playlists.length} rows</p>
            </div>
            <DataTable
              bulkActionSlot={
                <>
                  <ActionButton
                    className="inline-flex items-center gap-1.5"
                    disabled={selectedRows.length === 0 || isBulkUpdating}
                    onClick={() => void handleBulkSelectionUpdate(true)}
                  >
                    <CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
                    {isBulkUpdating ? "Updating..." : "Enable sync"}
                  </ActionButton>
                  <ActionButton
                    className="inline-flex items-center gap-1.5"
                    disabled={selectedRows.length === 0 || isBulkUpdating}
                    onClick={() => void handleBulkSelectionUpdate(false)}
                  >
                    <XCircle aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
                    {isBulkUpdating ? "Updating..." : "Disable sync"}
                  </ActionButton>
                  <ActionButton
                    className="inline-flex items-center gap-1.5"
                    disabled={hasAccountAuthError || selectedRows.length === 0 || isBulkSyncingRows}
                    onClick={() => void handleBulkRowSync()}
                  >
                    <RefreshCw aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
                    {isBulkSyncingRows ? "Syncing..." : "Sync rows"}
                  </ActionButton>
                </>
              }
              columns={columns}
              data={playlists}
              rowId={(playlist) => String(playlist.id)}
              rowSelection={rowSelection}
              sorting={sorting}
              stickyHeader
              onRowSelectionChange={setRowSelection}
              onSortingChange={setSorting}
            />
          </div>
        </div>
      </div>
    </section>
  );
}
