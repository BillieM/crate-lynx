import { FormEvent, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CirclePause, Play, RefreshCw, ShieldCheck } from "lucide-react";

import { ActionButton } from "../../components/ActionButton";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { MetricCard } from "../../components/MetricCard";
import { Pill, type PillTone } from "../../components/Pill";
import { StatusMessage } from "../../components/StatusMessage";
import { formatPlaylistTimestamp } from "../../lib/formatters";
import { controlClasses, layoutClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import {
  type AutopilotRun,
  type AutopilotRunItem,
  type AutopilotSettings,
  type UpdateAutopilotSettingsRequest,
  useAutopilotRunQuery,
  useAutopilotRunsQuery,
  useAutopilotSettingsQuery,
  useRunAutopilotDryRunMutation,
  useUpdateAutopilotSettingsMutation,
} from "./queries";

type SettingsDraft = {
  maxConcurrentDownloads: string;
  maxDownloadsPerRun: string;
  maxSearchesPerRun: string;
  maxStorageGbPerRun: string;
  paused: boolean;
  quietPeriodMinutes: string;
  retryBaseSeconds: string;
  retryMaxAttempts: string;
  retryMaxSeconds: string;
  scheduleMinutes: string;
};

const bytesPerGigabyte = 1_000_000_000;

function settingsToDraft(settings: AutopilotSettings): SettingsDraft {
  return {
    maxConcurrentDownloads: String(settings.max_concurrent_downloads),
    maxDownloadsPerRun: String(settings.max_downloads_per_run),
    maxSearchesPerRun: String(settings.max_searches_per_run),
    maxStorageGbPerRun: String(Number((settings.max_storage_bytes_per_run / bytesPerGigabyte).toFixed(2))),
    paused: settings.paused,
    quietPeriodMinutes: String(Math.round(settings.quiet_period_seconds / 60)),
    retryBaseSeconds: String(settings.retry_base_seconds),
    retryMaxAttempts: String(settings.retry_max_attempts),
    retryMaxSeconds: String(settings.retry_max_seconds),
    scheduleMinutes: String(settings.schedule_minutes),
  };
}

function draftToSettings(draft: SettingsDraft): UpdateAutopilotSettingsRequest {
  return {
    max_concurrent_downloads: readBoundedInteger(draft.maxConcurrentDownloads, 1, 32),
    max_downloads_per_run: readBoundedInteger(draft.maxDownloadsPerRun, 0, 10_000),
    max_searches_per_run: readBoundedInteger(draft.maxSearchesPerRun, 0, 10_000),
    max_storage_bytes_per_run: Math.round(readBoundedNumber(draft.maxStorageGbPerRun, 0, 10_000) * bytesPerGigabyte),
    paused: draft.paused,
    quiet_period_seconds: readBoundedInteger(draft.quietPeriodMinutes, 0, 1_440) * 60,
    retry_base_seconds: readBoundedInteger(draft.retryBaseSeconds, 1, 86_400),
    retry_max_attempts: readBoundedInteger(draft.retryMaxAttempts, 1, 20),
    retry_max_seconds: readBoundedInteger(draft.retryMaxSeconds, 1, 604_800),
    schedule_minutes: readBoundedInteger(draft.scheduleMinutes, 1, 10_080),
  };
}

export function AutopilotSettingsView() {
  const settingsQuery = useAutopilotSettingsQuery();
  const runsQuery = useAutopilotRunsQuery();
  const updateSettingsMutation = useUpdateAutopilotSettingsMutation();
  const pauseMutation = useUpdateAutopilotSettingsMutation();
  const dryRunMutation = useRunAutopilotDryRunMutation();
  const [draft, setDraft] = useState<SettingsDraft | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const runs = runsQuery.data?.runs ?? [];
  const latestRun = runs[0] ?? null;
  const effectiveSelectedRunId = selectedRunId ?? latestRun?.id ?? null;
  const selectedRunQuery = useAutopilotRunQuery(effectiveSelectedRunId);
  const selectedRun =
    selectedRunQuery.data ??
    runs.find((run) => run.id === effectiveSelectedRunId) ??
    latestRun;

  useEffect(() => {
    if (settingsQuery.data && draft === null) {
      setDraft(settingsToDraft(settingsQuery.data));
    }
  }, [draft, settingsQuery.data]);

  useEffect(() => {
    if (dryRunMutation.data) {
      setSelectedRunId(dryRunMutation.data.id);
    }
  }, [dryRunMutation.data]);

  const reviewItems = useMemo(
    () => selectedRun?.items.filter(itemNeedsReview) ?? [],
    [selectedRun?.items],
  );
  const failureItems = useMemo(
    () => selectedRun?.items.filter(itemIsFailure) ?? [],
    [selectedRun?.items],
  );

  function updateDraft<Key extends keyof SettingsDraft>(key: Key, value: SettingsDraft[Key]) {
    setDraft((current) => (current ? { ...current, [key]: value } : current));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft) {
      return;
    }

    updateSettingsMutation.mutate(draftToSettings(draft), {
      onSuccess: (settings) => setDraft(settingsToDraft(settings)),
    });
  }

  function handlePauseChange(paused: boolean) {
    const previousPaused = draft?.paused ?? false;
    updateDraft("paused", paused);
    pauseMutation.mutate(
      { paused },
      {
        onError: () => updateDraft("paused", previousPaused),
        onSuccess: (settings) => updateDraft("paused", settings.paused),
      },
    );
  }

  if (settingsQuery.isPending || runsQuery.isPending || draft === null) {
    return (
      <EmptyStateCard
        body="Loading the global pause state, safety caps, schedule, and recent runs."
        className={layoutClasses.emptyStateNarrow}
        title="Loading autopilot"
      />
    );
  }

  if (settingsQuery.isError || runsQuery.isError) {
    return (
      <EmptyStateCard
        body="Autopilot settings or operational history could not be loaded."
        className={layoutClasses.emptyStateNarrow}
        title="Autopilot unavailable"
        tone="error"
      />
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className={textClasses.sectionTitle}>Autopilot</h2>
          <p className={`mt-1 max-w-3xl ${textClasses.bodyMuted}`}>
            Keep explicitly selected YouTube Music playlists, acquisitions, analysis, saved crates, and configured
            exports current. Full automatic downloading still requires a per-playlist Full autopilot opt-in.
          </p>
        </div>
        <ActionButton
          disabled={dryRunMutation.isPending}
          onClick={() => dryRunMutation.mutate()}
          type="button"
        >
          <ShieldCheck aria-hidden="true" className="h-4 w-4" />
          {dryRunMutation.isPending ? "Planning…" : "Run safe dry-run"}
        </ActionButton>
      </div>

      {dryRunMutation.isError ? (
        <StatusMessage
          body="The dry-run could not be queued. No downloads or exports were changed."
          status="error"
          title="Dry-run failed"
        />
      ) : dryRunMutation.isSuccess ? (
        <StatusMessage
          body="The coordinator planned refreshes, searches, gates, and affected recipes without downloading, linking, regenerating, or writing exports."
          status="success"
          title="Dry-run queued"
        />
      ) : null}

      <section
        className={`${surfaceClasses.compactCard} grid gap-3 ${
          draft.paused ? "border-ctp-yellow/40 bg-ctp-yellow/5" : ""
        }`}
        aria-label="Autopilot global control"
      >
        <label className="flex cursor-pointer items-start gap-3">
          <input
            checked={draft.paused}
            className="mt-1 h-4 w-4 accent-ctp-yellow"
            disabled={pauseMutation.isPending}
            onChange={(event) => handlePauseChange(event.currentTarget.checked)}
            type="checkbox"
          />
          <span>
            <span className={`flex items-center gap-2 ${textClasses.title}`}>
              <CirclePause aria-hidden="true" className="h-4 w-4 text-ctp-yellow" />
              Global pause / kill switch
            </span>
            <span className={`mt-1 block ${textClasses.bodyMuted}`}>
              Saves immediately and stops new automatic work. Manual sync and manually approved acquisitions remain
              available.
            </span>
          </span>
        </label>
        {pauseMutation.isError ? (
          <StatusMessage
            body="The pause state could not be saved, so the switch was restored."
            status="error"
            title="Pause update failed"
          />
        ) : null}
      </section>

      <form className={`${surfaceClasses.compactCard} grid gap-4`} onSubmit={handleSubmit}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className={textClasses.label}>Schedule and safety bounds</h3>
            <p className={`mt-1 ${textClasses.caption}`}>
              Caps apply to unattended work. Retries remain bounded and regeneration waits for a quiet period.
            </p>
          </div>
          <ActionButton disabled={updateSettingsMutation.isPending} type="submit">
            {updateSettingsMutation.isPending ? "Saving…" : "Save automation settings"}
          </ActionButton>
        </div>

        {updateSettingsMutation.isError ? (
          <StatusMessage body="The automation settings could not be saved." status="error" title="Settings save failed" />
        ) : updateSettingsMutation.isSuccess ? (
          <StatusMessage body="The next coordinator run will use these bounds." status="success" title="Settings saved" />
        ) : null}

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <SettingsNumberInput
            help="How often the overlap-safe coordinator wakes."
            label="Run every (minutes)"
            min={1}
            onChange={(value) => updateDraft("scheduleMinutes", value)}
            value={draft.scheduleMinutes}
          />
          <SettingsNumberInput
            help="Debounce before affected recipes and exports refresh."
            label="Quiet period (minutes)"
            min={0}
            onChange={(value) => updateDraft("quietPeriodMinutes", value)}
            value={draft.quietPeriodMinutes}
          />
          <SettingsNumberInput
            help="Maximum transfers active at once."
            label="Concurrent downloads"
            min={1}
            onChange={(value) => updateDraft("maxConcurrentDownloads", value)}
            value={draft.maxConcurrentDownloads}
          />
          <SettingsNumberInput
            help="Maximum missing tracks to look up in one run. Set to 0 to refresh and reconcile without acquisition searches."
            label="Missing-track searches per run"
            min={0}
            onChange={(value) => updateDraft("maxSearchesPerRun", value)}
            value={draft.maxSearchesPerRun}
          />
          <SettingsNumberInput
            help="Hard download count cap for each coordinator run."
            label="Downloads per run"
            min={0}
            onChange={(value) => updateDraft("maxDownloadsPerRun", value)}
            value={draft.maxDownloadsPerRun}
          />
          <SettingsNumberInput
            help="Hard unattended transfer budget for each run."
            label="Storage per run (GB)"
            min={0}
            onChange={(value) => updateDraft("maxStorageGbPerRun", value)}
            step="0.1"
            value={draft.maxStorageGbPerRun}
          />
          <SettingsNumberInput
            help="Number of bounded retries after the first attempt."
            label="Retry attempts"
            min={1}
            onChange={(value) => updateDraft("retryMaxAttempts", value)}
            value={draft.retryMaxAttempts}
          />
          <SettingsNumberInput
            help="Initial exponential backoff delay."
            label="Retry base (seconds)"
            min={1}
            onChange={(value) => updateDraft("retryBaseSeconds", value)}
            value={draft.retryBaseSeconds}
          />
          <SettingsNumberInput
            help="Maximum delay between bounded retries."
            label="Retry ceiling (seconds)"
            min={1}
            onChange={(value) => updateDraft("retryMaxSeconds", value)}
            value={draft.retryMaxSeconds}
          />
        </div>
      </form>

      <RunSummary run={latestRun} />

      <section className={`${surfaceClasses.compactCard} grid gap-3`} aria-label="Autopilot run history">
        <div>
          <h3 className={textClasses.label}>Operational history</h3>
          <p className={`mt-1 ${textClasses.caption}`}>
            Routine successes stay compact. Select a run to inspect failures and items needing review.
          </p>
        </div>
        {runs.length > 0 ? (
          <div className="grid gap-3 lg:grid-cols-[minmax(16rem,0.7fr)_minmax(22rem,1.3fr)]">
            <div className="grid content-start gap-2">
              {runs.map((run) => (
                <button
                  aria-pressed={effectiveSelectedRunId === run.id}
                  className={`${surfaceClasses.rowCardCompact} text-left transition-colors ${
                    effectiveSelectedRunId === run.id
                      ? "border-ctp-mauve/60 bg-ctp-mauve/10"
                      : "hover:border-ctp-surface2"
                  }`}
                  key={run.id}
                  onClick={() => setSelectedRunId(run.id)}
                  type="button"
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className={textClasses.title}>
                      {run.dry_run ? "Dry-run" : "Autopilot"} #{run.id}
                    </span>
                    <Pill tone={runTone(run.status)}>{run.status}</Pill>
                  </span>
                  <span className={`mt-1 block ${textClasses.caption}`}>
                    {formatPlaylistTimestamp(run.started_at ?? run.created_at)} · {run.trigger}
                  </span>
                </button>
              ))}
            </div>
            <RunDetails
              failureItems={failureItems}
              isLoading={selectedRunQuery.isPending}
              reviewItems={reviewItems}
              run={selectedRun}
            />
          </div>
        ) : (
          <EmptyStateCard
            body="Use Run safe dry-run to refresh, search, and record gate evidence without downloading, ingesting, linking, regenerating, or exporting."
            className="text-left"
            title="No autopilot runs yet"
          />
        )}
      </section>
    </div>
  );
}

function RunSummary({ run }: { run: AutopilotRun | null }) {
  if (!run) {
    return null;
  }

  return (
    <section className={`${surfaceClasses.compactCard} grid gap-3`} aria-label="Last autopilot run summary">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className={textClasses.label}>Last run</h3>
          <p className={`mt-1 ${textClasses.caption}`}>
            {formatPlaylistTimestamp(run.started_at ?? run.created_at)} · {run.dry_run ? "safe dry-run" : run.trigger}
          </p>
        </div>
        <Pill tone={runTone(run.status)}>{run.status}</Pill>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <MetricCard
          icon={RefreshCw}
          label="Playlists refreshed"
          toneClass="bg-ctp-blue/10 text-ctp-blue ring-ctp-blue/25"
          value={getRunCount(run, "refreshed_playlists", "playlists_refreshed").toLocaleString()}
        />
        <MetricCard
          icon={Play}
          label="Downloaded"
          toneClass="bg-ctp-green/10 text-ctp-green ring-ctp-green/25"
          value={getRunCount(run, "downloaded_tracks", "downloaded").toLocaleString()}
        />
        <MetricCard
          icon={RefreshCw}
          label="Analyzed"
          toneClass="bg-ctp-mauve/10 text-ctp-mauve ring-ctp-mauve/25"
          value={getRunCount(run, "analyzed_tracks", "analyzed").toLocaleString()}
        />
        <MetricCard
          icon={RefreshCw}
          label="Recipes regenerated"
          toneClass="bg-ctp-teal/10 text-ctp-teal ring-ctp-teal/25"
          value={getRunCount(run, "regenerated_recipes", "recipes_regenerated").toLocaleString()}
        />
        <MetricCard
          icon={AlertTriangle}
          label="Needs review"
          toneClass="bg-ctp-yellow/10 text-ctp-yellow ring-ctp-yellow/25"
          value={getRunCount(run, "review_items", "needs_review").toLocaleString()}
        />
      </div>
      <p className={textClasses.caption}>
        Searched {getRunCount(run, "searched_tracks", "searched").toLocaleString()} · queued{" "}
        {getRunCount(run, "queued_downloads").toLocaleString()} · ingested{" "}
        {getRunCount(run, "ingested_tracks", "ingested").toLocaleString()} · exports refreshed{" "}
        {getRunCount(run, "refreshed_exports", "exports_refreshed").toLocaleString()} · failures{" "}
        {getRunCount(run, "failed_items", "failures").toLocaleString()}
      </p>
    </section>
  );
}

function RunDetails({
  failureItems,
  isLoading,
  reviewItems,
  run,
}: {
  failureItems: AutopilotRunItem[];
  isLoading: boolean;
  reviewItems: AutopilotRunItem[];
  run: AutopilotRun | null;
}) {
  if (!run || isLoading) {
    return <p className={textClasses.bodyMuted}>Loading run details…</p>;
  }

  return (
    <div className="grid content-start gap-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <CompactCount label="Refreshed" value={getRunCount(run, "refreshed_playlists", "playlists_refreshed")} />
        <CompactCount label="Searched" value={getRunCount(run, "searched_tracks", "searched")} />
        <CompactCount label="Queued" value={getRunCount(run, "queued_downloads")} />
        <CompactCount label="Downloaded" value={getRunCount(run, "downloaded_tracks", "downloaded")} />
        <CompactCount label="Ingested" value={getRunCount(run, "ingested_tracks", "ingested")} />
        <CompactCount label="Analyzed" value={getRunCount(run, "analyzed_tracks", "analyzed")} />
        <CompactCount label="Recipes" value={getRunCount(run, "regenerated_recipes", "recipes_regenerated")} />
        <CompactCount label="Exports" value={getRunCount(run, "refreshed_exports", "exports_refreshed")} />
      </div>
      {failureItems.length > 0 ? (
        <RunItemList items={failureItems} label="Failures" tone="danger" />
      ) : null}
      {reviewItems.length > 0 ? (
        <RunItemList items={reviewItems} label="Needs review" tone="warning" />
      ) : null}
      {failureItems.length === 0 && reviewItems.length === 0 ? (
        <p className={`${surfaceClasses.insetPanel} p-3 ${textClasses.bodyMuted}`}>
          No failures or review-required items were recorded for this run.
        </p>
      ) : null}
    </div>
  );
}

function RunItemList({
  items,
  label,
  tone,
}: {
  items: AutopilotRunItem[];
  label: string;
  tone: "danger" | "warning";
}) {
  return (
    <section
      className={`rounded-[8px] border p-3 ${
        tone === "danger" ? "border-ctp-red/35 bg-ctp-red/5" : "border-ctp-yellow/35 bg-ctp-yellow/5"
      }`}
    >
      <h4 className={`${textClasses.label} ${tone === "danger" ? "text-ctp-red" : "text-ctp-yellow"}`}>
        {label} ({items.length})
      </h4>
      <ul className="mt-2 grid gap-2">
        {items.map((item, index) => (
          <li className={textClasses.caption} key={item.id ?? `${item.status}-${index}`}>
            <span className="font-semibold text-ctp-text">{item.stage ?? item.status}</span>
            {item.reason ? ` · ${item.reason}` : ""}
            {item.detail ? ` · ${item.detail}` : ""}
          </li>
        ))}
      </ul>
    </section>
  );
}

function SettingsNumberInput({
  help,
  label,
  min,
  onChange,
  step = "1",
  value,
}: {
  help: string;
  label: string;
  min: number;
  onChange: (value: string) => void;
  step?: string;
  value: string;
}) {
  const inputId = `autopilot-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  return (
    <label className="grid gap-1.5" htmlFor={inputId}>
      <span className={textClasses.label}>{label}</span>
      <input
        aria-label={label}
        className={`${controlClasses.searchFrame} min-h-10 px-3 text-ctp-text outline-none ${textClasses.input}`}
        id={inputId}
        min={min}
        onChange={(event) => onChange(event.currentTarget.value)}
        step={step}
        type="number"
        value={value}
      />
      <span className={textClasses.caption}>{help}</span>
    </label>
  );
}

function CompactCount({ label, value }: { label: string; value: number }) {
  return (
    <div className={surfaceClasses.insetPanel + " p-2.5"}>
      <p className={textClasses.finePrint}>{label}</p>
      <p className="mt-0.5 text-[14px] font-semibold tabular-nums text-ctp-text">{value.toLocaleString()}</p>
    </div>
  );
}

function getRunCount(run: AutopilotRun, ...keys: string[]) {
  for (const key of keys) {
    const value = run.counts[key];
    if (typeof value === "number") {
      return value;
    }
  }
  return 0;
}

function itemIsFailure(item: AutopilotRunItem) {
  return ["corrupt", "error", "failed", "mismatch"].some((status) =>
    item.status.toLocaleLowerCase().includes(status),
  );
}

function itemNeedsReview(item: AutopilotRunItem) {
  if (itemIsFailure(item)) {
    return false;
  }

  return ["ambiguous", "exception", "needs_review", "review"].some((status) =>
    item.status.toLocaleLowerCase().includes(status),
  );
}

function runTone(status: string): PillTone {
  if (status === "completed" || status === "success" || status === "succeeded") {
    return "success";
  }
  if (status === "failed") {
    return "danger";
  }
  if (status === "partial" || status === "paused") {
    return "pending";
  }
  return status === "pending" || status === "running" ? "pending" : "neutral";
}

function readBoundedInteger(value: string, min: number, max: number) {
  return Math.round(readBoundedNumber(value, min, max));
}

function readBoundedNumber(value: string, min: number, max: number) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return min;
  }
  return Math.max(min, Math.min(max, parsed));
}
