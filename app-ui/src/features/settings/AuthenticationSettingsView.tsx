import { FormEvent, useMemo, useState } from "react";
import { Info } from "lucide-react";
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

type HeaderEntry = readonly [string, string];

const devToolsMetadataHeaders = new Set([
  "general",
  "provisional headers are shown",
  "referer policy",
  "referrer policy",
  "remote address",
  "request method",
  "request url",
  "response headers",
  "status code",
]);

function formatAccountTimestamp(timestamp: string | null) {
  if (!timestamp) {
    return "Unknown time";
  }

  return timestamp.replace("T", " ").replace(/(?:\.\d+)?Z?$/, "");
}

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseHeaderArray(headers: unknown): HeaderEntry[] | null {
  if (!Array.isArray(headers)) {
    return null;
  }

  const entries = headers.flatMap((header) => {
    if (!isRecord(header) || typeof header.name !== "string") {
      return [];
    }

    return [[header.name, String(header.value ?? "")] as const];
  });

  return entries.length > 0 ? entries : null;
}

function parseHeaderRecord(headers: unknown): HeaderEntry[] | null {
  if (!isRecord(headers)) {
    return null;
  }

  const entries = Object.entries(headers).flatMap(([name, value]) => {
    if (isRecord(value) || Array.isArray(value)) {
      return [];
    }

    return [[name, String(value)] as const];
  });

  return entries.length > 0 ? entries : null;
}

function parseJsonHeaderEntries(parsedHeaders: unknown): HeaderEntry[] | null {
  if (!isRecord(parsedHeaders)) {
    return null;
  }

  const nestedHeaderSources = [
    parsedHeaders.browser_headers,
    parsedHeaders.headers,
    isRecord(parsedHeaders.request) ? parsedHeaders.request.headers : null,
    isRecord(parsedHeaders.log) &&
    Array.isArray(parsedHeaders.log.entries) &&
    isRecord(parsedHeaders.log.entries[0]) &&
    isRecord(parsedHeaders.log.entries[0].request)
      ? parsedHeaders.log.entries[0].request.headers
      : null,
  ];

  for (const source of nestedHeaderSources) {
    const entries = parseHeaderArray(source) ?? parseHeaderRecord(source);

    if (entries) {
      return entries;
    }
  }

  return parseHeaderRecord(parsedHeaders);
}

function normalizeHeaderEntries(headerEntries: HeaderEntry[]): Record<string, string> {
  const headers = Object.fromEntries(
    headerEntries.flatMap(([rawName, rawValue]) => {
      const name = rawName.trim().toLowerCase();
      const value = rawValue.trim();

      if (!name || name.startsWith(":") || !value || devToolsMetadataHeaders.has(name)) {
        return [];
      }

      return [[name, value] as const];
    }),
  );

  if (Object.keys(headers).length === 0) {
    throw new Error("Paste a cURL request copied from DevTools.");
  }

  return headers;
}

function splitShellWords(command: string): string[] {
  const words: string[] = [];
  let current = "";
  let quote: "'" | '"' | null = null;
  let escaped = false;

  for (const character of command.replace(/\\\r?\n/g, " ")) {
    if (escaped) {
      current += character;
      escaped = false;
      continue;
    }

    if (character === "\\" && quote !== "'") {
      escaped = true;
      continue;
    }

    if ((character === "'" || character === '"') && quote === null) {
      quote = character;
      continue;
    }

    if (character === quote) {
      quote = null;
      continue;
    }

    if (/\s/.test(character) && quote === null) {
      if (current) {
        words.push(current);
        current = "";
      }
      continue;
    }

    current += character;
  }

  if (current) {
    words.push(current);
  }

  return words;
}

function parseCurlHeaderEntries(command: string): HeaderEntry[] | null {
  const words = splitShellWords(command);
  const entries: HeaderEntry[] = [];

  for (let index = 0; index < words.length; index += 1) {
    const word = words[index];
    let headerValue: string | null = null;
    let cookieValue: string | null = null;

    if (word === "-H" || word === "--header") {
      headerValue = words[index + 1] ?? "";
      index += 1;
    } else if (word.startsWith("--header=")) {
      headerValue = word.slice("--header=".length);
    } else if (word.startsWith("-H") && word.length > 2) {
      headerValue = word.slice(2);
    } else if (word === "-b" || word === "--cookie" || word === "--cookie-raw") {
      cookieValue = words[index + 1] ?? "";
      index += 1;
    } else if (word.startsWith("--cookie=")) {
      cookieValue = word.slice("--cookie=".length);
    } else if (word.startsWith("-b") && word.length > 2) {
      cookieValue = word.slice(2);
    }

    if (headerValue !== null) {
      const separatorIndex = headerValue.indexOf(":");

      if (separatorIndex > 0) {
        entries.push([
          headerValue.slice(0, separatorIndex),
          headerValue.slice(separatorIndex + 1),
        ]);
      }
    }

    if (cookieValue !== null) {
      entries.push(["cookie", cookieValue]);
    }
  }

  return entries.length > 0 ? entries : null;
}

function parseHeaderLineEntries(rawHeaders: string): HeaderEntry[] | null {
  const entries = rawHeaders
    .replace(/\\\r?\n/g, "\n")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .flatMap((line) => {
      const separatorIndex = line.indexOf(":");

      if (separatorIndex <= 0) {
        return [];
      }

      return [[line.slice(0, separatorIndex), line.slice(separatorIndex + 1)] as const];
    });

  return entries.length > 0 ? entries : null;
}

function parseBrowserHeaders(rawHeaders: string): Record<string, unknown> {
  const trimmedHeaders = rawHeaders.trim();

  if (!trimmedHeaders) {
    throw new Error("Paste a cURL request copied from DevTools.");
  }

  if (trimmedHeaders.startsWith("{")) {
    let parsedHeaders: unknown;

    try {
      parsedHeaders = JSON.parse(trimmedHeaders) as unknown;
    } catch {
      throw new Error("Paste a valid cURL request copied from DevTools.");
    }

    const entries = parseJsonHeaderEntries(parsedHeaders);

    if (entries) {
      return normalizeHeaderEntries(entries);
    }
  }

  const curlEntries = trimmedHeaders.toLowerCase().startsWith("curl ")
    ? parseCurlHeaderEntries(trimmedHeaders)
    : null;
  const headerLineEntries = curlEntries ?? parseHeaderLineEntries(trimmedHeaders);

  if (headerLineEntries) {
    return normalizeHeaderEntries(headerLineEntries);
  }

  throw new Error("Paste a cURL request copied from DevTools.");
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
      body: `${account.auth_error ?? "The YouTube Music session needs a fresh cURL request."} Last failure: ${formatAccountTimestamp(account.auth_error_at)}.`,
      status: "error",
      title: "Authentication needs attention",
    };
  }

  return {
    body: `${account.display_name} authentication has been saved. The next playlist sync will verify whether this YouTube Music session still works.`,
    status: "pending",
    title: "Saved, not verified",
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
        body: "Refreshing YouTube Music authentication from the copied cURL request.",
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
      setValidationError(getErrorMessage(error, "The cURL request could not be parsed."));
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
          <p className={`mt-1 ${textClasses.bodyMuted}`}>YouTube Music authentication from a copied cURL request.</p>
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
            <section
              aria-labelledby="youtube-music-header-help"
              className={`${surfaceClasses.statusPanel} border-ctp-blue/30 bg-ctp-blue/10 text-ctp-blue`}
            >
              <div className="flex gap-2">
                <Info aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
                <div className="grid gap-1.5">
                  <h3 className={textClasses.label} id="youtube-music-header-help">
                    How to copy the cURL request
                  </h3>
                  <p className={textClasses.bodyRelaxed}>
                    Open YouTube Music, open DevTools Network, select a request to music.youtube.com/youtubei, then
                    right-click and choose Copy &gt; Copy as cURL. Paste the whole cURL command below.
                  </p>
                </div>
              </div>
            </section>

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
              <span className={textClasses.label}>cURL request</span>
              <textarea
                className={`${controlClasses.searchFrame} min-h-[10rem] resize-y px-3 py-2 font-mono text-[12px] leading-5 text-ctp-text outline-none placeholder:text-ctp-overlay1`}
                disabled={isSubmitting}
                id="youtube-music-browser-headers"
                onChange={(event) => setBrowserHeaders(event.target.value)}
                placeholder={"curl 'https://music.youtube.com/youtubei/...' -H 'authorization: SAPISIDHASH ...' -H 'cookie: ...'"}
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
