import { FormEvent, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ActionButton } from "../../components/ActionButton";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { StatusMessage, type OperationStatus } from "../../components/StatusMessage";
import { controlClasses, layoutClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import {
  type StreamingAccount,
  useCreateStreamingAccountMutation,
  useRefreshStreamingAccountAuthMutation,
  useStreamingAccountsQuery,
} from "../streamingAccounts/queries";

type AuthenticationMutationMessage = {
  body: string;
  status: OperationStatus;
  title: string;
};

function formatAccountTimestamp(timestamp: string | null) {
  if (!timestamp) {
    return "Unknown time";
  }

  return timestamp.replace("T", " ").replace(/(?:\.\d+)?Z?$/, "");
}

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function parseBrowserHeaders(rawHeaders: string): Record<string, unknown> {
  const trimmedHeaders = rawHeaders.trim();

  if (!trimmedHeaders) {
    throw new Error("Browser headers are required.");
  }

  try {
    const parsedHeaders = JSON.parse(trimmedHeaders) as unknown;

    if (parsedHeaders && typeof parsedHeaders === "object" && !Array.isArray(parsedHeaders)) {
      return parsedHeaders as Record<string, unknown>;
    }
  } catch {
    const headerEntries = trimmedHeaders
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const separatorIndex = line.indexOf(":");

        if (separatorIndex <= 0) {
          throw new Error("Browser headers must be a JSON object or header-name: value lines.");
        }

        return [line.slice(0, separatorIndex).trim(), line.slice(separatorIndex + 1).trim()] as const;
      });

    if (headerEntries.length > 0) {
      return Object.fromEntries(headerEntries);
    }
  }

  throw new Error("Browser headers must be a JSON object or header-name: value lines.");
}

function getActiveYouTubeMusicAccount(accounts: StreamingAccount[]) {
  return accounts.find((account) => account.provider === "youtube_music") ?? null;
}

function AuthenticationSettingsState({ status }: { status: "error" | "loading" }) {
  const copy = {
    error: {
      title: "Authentication unavailable",
      body: "Streaming account authentication could not be loaded. Try again after the backend is reachable.",
      tone: "error",
    },
    loading: {
      title: "Loading authentication",
      body: "Checking the saved YouTube Music connection.",
      tone: "neutral",
    },
  } as const;
  const state = copy[status];

  return (
    <div className="flex min-h-0 flex-1 items-center justify-center">
      <EmptyStateCard
        body={state.body}
        className={layoutClasses.emptyStateNarrow}
        role={status === "loading" ? "status" : "alert"}
        title={state.title}
        tone={state.tone}
      />
    </div>
  );
}

function getAccountStatusMessage(account: StreamingAccount | null): AuthenticationMutationMessage {
  if (!account) {
    return {
      body: "No YouTube Music account is connected.",
      status: "pending",
      title: "Not connected",
    };
  }

  if (account.auth_state === "error" || account.auth_error) {
    return {
      body: `${account.auth_error ?? "The YouTube Music session needs fresh browser headers."} Last failure: ${formatAccountTimestamp(account.auth_error_at)}.`,
      status: "error",
      title: "Authentication needs attention",
    };
  }

  return {
    body: `${account.display_name} is ready for YouTube Music sync.`,
    status: "success",
    title: "Connected",
  };
}

export function AuthenticationSettingsView() {
  const navigate = useNavigate();
  const accountsQuery = useStreamingAccountsQuery();
  const createAccountMutation = useCreateStreamingAccountMutation();
  const refreshAuthMutation = useRefreshStreamingAccountAuthMutation();
  const [displayName, setDisplayName] = useState("YouTube Music");
  const [browserHeaders, setBrowserHeaders] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const activeAccount = getActiveYouTubeMusicAccount(accountsQuery.data?.accounts ?? []);
  const trimmedDisplayName = displayName.trim();
  const trimmedBrowserHeaders = browserHeaders.trim();
  const isExistingAccount = activeAccount !== null;
  const isSubmitting = createAccountMutation.isPending || refreshAuthMutation.isPending;
  const accountStatusMessage = getAccountStatusMessage(activeAccount);
  const mutationMessage = useMemo<AuthenticationMutationMessage | null>(() => {
    if (validationError) {
      return {
        body: validationError,
        status: "error",
        title: "Authentication not saved",
      };
    }

    if (createAccountMutation.isPending) {
      return {
        body: "Saving the YouTube Music account.",
        status: "pending",
        title: "Connecting authentication",
      };
    }

    if (refreshAuthMutation.isPending) {
      return {
        body: "Refreshing the YouTube Music browser headers.",
        status: "pending",
        title: "Refreshing authentication",
      };
    }

    if (createAccountMutation.isError) {
      return {
        body: getErrorMessage(createAccountMutation.error, "The YouTube Music account could not be connected."),
        status: "error",
        title: "Connect failed",
      };
    }

    if (refreshAuthMutation.isError) {
      return {
        body: getErrorMessage(refreshAuthMutation.error, "The YouTube Music account authentication could not be refreshed."),
        status: "error",
        title: "Refresh failed",
      };
    }

    if (createAccountMutation.isSuccess || refreshAuthMutation.isSuccess) {
      return {
        body: "YouTube Music authentication was saved.",
        status: "success",
        title: "Authentication saved",
      };
    }

    return null;
  }, [
    createAccountMutation.error,
    createAccountMutation.isError,
    createAccountMutation.isPending,
    createAccountMutation.isSuccess,
    refreshAuthMutation.error,
    refreshAuthMutation.isError,
    refreshAuthMutation.isPending,
    refreshAuthMutation.isSuccess,
    validationError,
  ]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (isSubmitting) {
      return;
    }

    let parsedBrowserHeaders: Record<string, unknown>;

    try {
      parsedBrowserHeaders = parseBrowserHeaders(browserHeaders);
      setValidationError(null);
    } catch (error) {
      setValidationError(getErrorMessage(error, "Browser headers could not be parsed."));
      return;
    }

    if (activeAccount) {
      refreshAuthMutation.mutate(
        {
          accountId: activeAccount.id,
          browser_headers: parsedBrowserHeaders,
        },
        {
          onSuccess: () => setBrowserHeaders(""),
        },
      );
      return;
    }

    createAccountMutation.mutate(
      {
        browser_headers: parsedBrowserHeaders,
        display_name: trimmedDisplayName || "YouTube Music",
      },
      {
        onSuccess: () => setBrowserHeaders(""),
      },
    );
  }

  if (accountsQuery.isPending) {
    return <AuthenticationSettingsState status="loading" />;
  }

  if (accountsQuery.isError) {
    return <AuthenticationSettingsState status="error" />;
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className={textClasses.sectionTitle}>Authentication settings</h2>
          <p className={`mt-1 ${textClasses.bodyMuted}`}>YouTube Music browser-header authentication.</p>
        </div>
        {mutationMessage?.status === "success" ? (
          <ActionButton onClick={() => navigate("/settings/sync/youtube-music")}>Configure playlists</ActionButton>
        ) : null}
      </div>

      <div aria-label="Authentication form" className="min-h-0 flex-1 overflow-y-auto pb-1 pr-1" role="region">
        <div className="grid gap-3">
          <StatusMessage
            body={accountStatusMessage.body}
            status={accountStatusMessage.status}
            title={accountStatusMessage.title}
          />
          {mutationMessage ? (
            <StatusMessage body={mutationMessage.body} status={mutationMessage.status} title={mutationMessage.title} />
          ) : null}

          <form className={`${surfaceClasses.rowCardCompact} gap-3`} onSubmit={handleSubmit}>
            {!isExistingAccount ? (
              <label className="grid gap-1.5" htmlFor="youtube-music-display-name">
                <span className={textClasses.label}>Display name</span>
                <input
                  className={`${controlClasses.searchFrame} min-h-10 px-3 py-2 text-ctp-text outline-none placeholder:text-ctp-overlay1 ${textClasses.input}`}
                  disabled={isSubmitting}
                  id="youtube-music-display-name"
                  onChange={(event) => setDisplayName(event.target.value)}
                  type="text"
                  value={displayName}
                />
              </label>
            ) : (
              <div className="grid gap-1.5">
                <span className={textClasses.label}>Display name</span>
                <p className={textClasses.bodyMuted}>{activeAccount.display_name}</p>
              </div>
            )}

            <label className="grid gap-1.5" htmlFor="youtube-music-browser-headers">
              <span className={textClasses.label}>Browser headers</span>
              <textarea
                className={`${controlClasses.searchFrame} min-h-[10rem] resize-y px-3 py-2 font-mono text-[12px] leading-5 text-ctp-text outline-none placeholder:text-ctp-overlay1`}
                disabled={isSubmitting}
                id="youtube-music-browser-headers"
                onChange={(event) => setBrowserHeaders(event.target.value)}
                placeholder='{"Authorization":"Bearer ...","Cookie":"..."}'
                value={browserHeaders}
              />
            </label>

            <div className="flex flex-wrap justify-end gap-2">
              <ActionButton disabled={!trimmedBrowserHeaders || isSubmitting} type="submit">
                {isSubmitting ? "Saving..." : isExistingAccount ? "Refresh authentication" : "Connect"}
              </ActionButton>
            </div>
          </form>
        </div>
      </div>
    </section>
  );
}
