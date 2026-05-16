import { createColumnHelper, type SortingState } from "@tanstack/react-table";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Search, Settings2, XCircle } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import { ActionButton } from "../../components/ActionButton";
import { DataTable } from "../../components/DataTable";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { StatusMessage, type OperationStatus } from "../../components/StatusMessage";
import { formatPlaylistTimestamp } from "../../lib/formatters";
import { useDelayedInvalidate } from "../../lib/useDelayedInvalidate";
import { controlClasses, layoutClasses, textClasses } from "../../styles/componentClasses";
import { actionButtonToneClasses } from "../../styles/toneClasses";
import { PlaylistActionStatus } from "../shell/Topbar";
import {
  streamingAccountCollectionJobInvalidationKeys,
  streamingAccountPlaylistSyncJobInvalidationKeys,
  useStreamingAccountsQuery,
} from "../streamingAccounts/queries";
import {
  invalidatePlaylistConfigurationMutationQueries,
  refreshStreamingAccountMetadata,
  syncStreamingAccount,
  type PlaylistSyncMode,
  type StreamingPlaylistConfig,
  updateStreamingPlaylistConfig,
  useStreamingPlaylistConfigQuery,
} from "./queries";

type PlaylistCollectionStatus = "empty" | "error" | "loading" | "ready";
const emptyPlaylistConfigs: StreamingPlaylistConfig[] = [];

const activePlaylistSyncModes = new Set<PlaylistSyncMode>(["full", "match_only"]);
const playlistSyncModeLabels = {
  off: "Off",
  match_only: "Match only",
  full: "Full sync",
} satisfies Record<PlaylistSyncMode, string>;
const playlistSyncModeOptions = [
  { icon: XCircle, label: playlistSyncModeLabels.off, value: "off" },
  { icon: Search, label: playlistSyncModeLabels.match_only, value: "match_only" },
  { icon: CheckCircle2, label: playlistSyncModeLabels.full, value: "full" },
] satisfies Array<{ icon: typeof XCircle; label: string; value: PlaylistSyncMode }>;
const selectedSyncModeClasses = {
  off: "border-ctp-overlay0 bg-ctp-surface1 text-ctp-text shadow-sm",
  match_only: "border-ctp-blue/60 bg-ctp-blue/15 text-ctp-blue shadow-sm",
  full: "border-ctp-green/60 bg-ctp-green/15 text-ctp-green shadow-sm",
} satisfies Record<PlaylistSyncMode, string>;

function isActiveSyncMode(syncMode: PlaylistSyncMode) {
  return activePlaylistSyncModes.has(syncMode);
}

function getPlaylistModeCounts(playlists: StreamingPlaylistConfig[]) {
  return playlists.reduce(
    (counts, playlist) => {
      if (playlist.sync_mode === "full") {
        counts.full += 1;
      }

      if (playlist.sync_mode === "match_only") {
        counts.matchOnly += 1;
      }

      if (isActiveSyncMode(playlist.sync_mode)) {
        counts.active += 1;
      }

      return counts;
    },
    { active: 0, full: 0, matchOnly: 0 },
  );
}

function formatOptionalCount(value: number | null) {
  return value === null ? "Unknown" : value.toLocaleString();
}

const columnHelper = createColumnHelper<StreamingPlaylistConfig>();

function PlaylistCollectionState({
  actionSlot,
  status,
  statusSlot,
}: {
  actionSlot?: ReactNode;
  status: PlaylistCollectionStatus;
  statusSlot?: ReactNode;
}) {
  const copy = {
    empty: {
      title: "No playlists discovered",
      body: "Refresh YouTube Music metadata after authentication is configured, then choose sync modes for discovered playlists.",
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
      body: "Review discovered YouTube Music playlists and choose which ones import tracks or feed matching.",
    },
  } satisfies Record<PlaylistCollectionStatus, { body: string; title: string }>;

  return (
    <section className="flex min-h-0 flex-1 items-center justify-center">
      <div className="grid justify-items-center gap-3">
        <EmptyStateCard body={copy[status].body} className={layoutClasses.emptyStateNarrow} title={copy[status].title} />
        {statusSlot}
        {actionSlot}
      </div>
    </section>
  );
}

function PlaylistSyncModeControl({
  isPending,
  onChange,
  playlist,
}: {
  isPending: boolean;
  onChange: (syncMode: PlaylistSyncMode) => void;
  playlist: StreamingPlaylistConfig;
}) {
  return (
    <div
      aria-label={`Sync mode for ${playlist.title}`}
      className="inline-flex shrink-0 overflow-hidden rounded-[8px] border border-ctp-surface1 bg-ctp-surface0 p-0.5"
      role="group"
    >
      {playlistSyncModeOptions.map((option) => {
        const Icon = option.icon;
        const isSelected = playlist.sync_mode === option.value;

        return (
          <button
            key={option.value}
            aria-pressed={isSelected}
            className={`inline-flex min-h-7 min-w-[5.75rem] items-center justify-center gap-1.5 rounded-[7px] border px-2 text-[11px] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
              isSelected
                ? selectedSyncModeClasses[option.value]
                : "border-transparent text-ctp-subtext0 hover:bg-ctp-surface1 hover:text-ctp-text"
            }`}
            disabled={isPending || isSelected}
            type="button"
            onClick={() => onChange(option.value)}
          >
            <Icon aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            {isPending && isSelected ? "Updating..." : option.label}
          </button>
        );
      })}
    </div>
  );
}

export function PlaylistSyncConfiguration() {
  const queryClient = useQueryClient();
  const delayedInvalidate = useDelayedInvalidate();
  const configQuery = useStreamingPlaylistConfigQuery();
  const accountsQuery = useStreamingAccountsQuery();
  const [sorting, setSorting] = useState<SortingState>([]);
  const selectedSyncMutation = useMutation({
    mutationFn: syncStreamingAccount,
    onSuccess: async () => {
      await invalidatePlaylistConfigurationMutationQueries(queryClient);
      scheduleStreamingSyncRefresh(getEnabledPlaylistIds());
    },
  });
  const metadataRefreshMutation = useMutation({
    mutationFn: refreshStreamingAccountMetadata,
    onSuccess: async () => {
      await invalidatePlaylistConfigurationMutationQueries(queryClient);
      schedulePlaylistCollectionJobRefresh();
    },
  });
  const toggleMutation = useMutation({
    mutationFn: updateStreamingPlaylistConfig,
    onSuccess: async () => {
      await invalidatePlaylistConfigurationMutationQueries(queryClient);
    },
  });
  const accounts = accountsQuery.data?.accounts ?? [];
  const playlists = configQuery.data?.playlists ?? emptyPlaylistConfigs;
  const modeCounts = getPlaylistModeCounts(playlists);
  const playlistAccountId = playlists[0]?.account_id;
  const activeAccount =
    accounts.find((account) => account.id === playlistAccountId) ??
    accounts.find((account) => account.provider === "youtube_music") ??
    null;
  const accountId = playlistAccountId ?? activeAccount?.id;
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
  const operationMessage = selectedSyncMutation.isPending
    ? {
        body: "Full and match-only playlists are being synced. Sidebar counts and playlist views may update when the job finishes.",
        status: "pending",
        title: "Active playlist sync in progress",
      }
    : selectedSyncMutation.isError
      ? {
          body: "The active playlist sync request failed before a job could be queued.",
          status: "error",
          title: "Active playlist sync failed",
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
          <PlaylistSyncModeControl
            isPending={toggleMutation.isPending && toggleMutation.variables?.playlistId === info.row.original.id}
            onChange={(syncMode) =>
              toggleMutation.mutate({
                playlistId: info.row.original.id,
                sync_mode: syncMode,
              })
            }
            playlist={info.row.original}
          />
        ),
        header: "Mode",
        meta: {
          widthClass: "min-w-[18rem]",
        },
      }),
      columnHelper.accessor("provider_track_count", {
        cell: (info) => <span className="tabular-nums">{formatOptionalCount(info.getValue())}</span>,
        header: "YouTube count",
        meta: {
          align: "end",
          widthClass: "w-32",
        },
      }),
      columnHelper.accessor("imported_track_count", {
        cell: (info) => <span className="tabular-nums">{info.getValue().toLocaleString()}</span>,
        header: "Imported",
        meta: {
          align: "end",
          widthClass: "w-28",
        },
      }),
      columnHelper.accessor("metadata_synced_at", {
        cell: (info) => <span className="block max-w-[12rem] truncate">{formatPlaylistTimestamp(info.getValue())}</span>,
        header: "Metadata refreshed",
        meta: {
          hideBelow: "md",
          widthClass: "min-w-[12rem]",
        },
      }),
      columnHelper.accessor("tracks_synced_at", {
        cell: (info) => <span className="block max-w-[12rem] truncate">{formatPlaylistTimestamp(info.getValue())}</span>,
        header: "Tracks synced",
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
    ],
    [toggleMutation],
  );

  function getEnabledPlaylistIds() {
    return playlists.filter((playlist) => isActiveSyncMode(playlist.sync_mode)).map((playlist) => playlist.id);
  }

  function schedulePlaylistCollectionJobRefresh() {
    delayedInvalidate(streamingAccountCollectionJobInvalidationKeys());
  }

  function scheduleStreamingSyncRefresh(playlistIds: readonly (number | string)[]) {
    delayedInvalidate(streamingAccountPlaylistSyncJobInvalidationKeys(playlistIds));
  }

  if (configQuery.isPending) {
    return <PlaylistCollectionState status="loading" />;
  }

  if (configQuery.isError) {
    return <PlaylistCollectionState status="error" />;
  }

  if (playlists.length === 0) {
    const emptyActionSlot =
      activeAccount === null ? (
        <a className={`${controlClasses.actionButton} ${actionButtonToneClasses.neutral}`} href="/settings/authentication">
          Authentication
        </a>
      ) : accountAuthError ? (
        <a className={`${controlClasses.actionButton} ${actionButtonToneClasses.danger}`} href="/settings/authentication">
          Refresh authentication
        </a>
      ) : (
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
      );

    return (
      <PlaylistCollectionState
        actionSlot={emptyActionSlot}
        status="empty"
        statusSlot={
          <>
            {accountAuthError ? (
              <StatusMessage body={accountAuthError.body} status="error" title={accountAuthError.title} />
            ) : null}
            <PlaylistActionStatus
              errorText="Metadata refresh failed."
              isError={metadataRefreshMutation.isError}
              isPending={metadataRefreshMutation.isPending}
              isSuccess={metadataRefreshMutation.isSuccess}
              pendingText="Refreshing playlist metadata..."
              successText="Metadata refresh queued."
            />
          </>
        }
      />
    );
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className={textClasses.sectionTitle}>Playlist sync configuration</h2>
          <div className="mt-2 flex flex-wrap gap-2">
            <span className={`${controlClasses.countBadge} min-w-fit px-2.5 py-1`}>
              {playlists.length.toLocaleString()} discovered
            </span>
            <span className={`${controlClasses.countBadge} min-w-fit px-2.5 py-1 text-ctp-green`}>
              {modeCounts.full.toLocaleString()} full sync
            </span>
            <span className={`${controlClasses.countBadge} min-w-fit px-2.5 py-1 text-ctp-blue`}>
              {modeCounts.matchOnly.toLocaleString()} match only
            </span>
          </div>
        </div>
        <div className="flex flex-col items-start gap-2 sm:items-end">
          <div className="flex flex-wrap justify-start gap-2 sm:justify-end">
            <ActionButton
              disabled={
                hasAccountAuthError ||
                accountId === undefined ||
                modeCounts.active === 0 ||
                selectedSyncMutation.isPending
              }
              onClick={() => {
                if (accountId !== undefined) {
                  selectedSyncMutation.mutate(accountId);
                }
              }}
            >
              {selectedSyncMutation.isPending ? "Syncing Full + Match..." : "Sync Full + Match"}
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
            errorText="Active playlist sync failed."
            isError={selectedSyncMutation.isError}
            isPending={selectedSyncMutation.isPending}
            isSuccess={selectedSyncMutation.isSuccess}
            pendingText="Syncing Full + Match playlists..."
            successText="Full + Match playlist sync queued."
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
          <div className="grid gap-2.5">
            <div className="flex items-center justify-between gap-3 px-1">
              <div className="flex items-center gap-2 text-ctp-subtext0">
                <Settings2 aria-hidden="true" className="h-4 w-4" strokeWidth={1.8} />
                <h3 className={textClasses.label}>Discovered playlist rows</h3>
              </div>
              <p className={`${textClasses.caption} tabular-nums`}>{playlists.length} rows</p>
            </div>
            <DataTable
              columns={columns}
              data={playlists}
              enableRowSelection={false}
              rowId={(playlist) => String(playlist.id)}
              sorting={sorting}
              stickyHeader
              onSortingChange={setSorting}
            />
          </div>
        </div>
      </div>
    </section>
  );
}
