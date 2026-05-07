import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { jsonResponse } from "../../test/mockApi";
import {
  buildSettingsNavItems,
  getViewIdFromPath,
  getViewPath,
  settingsAuthenticationViewId,
  staticViewRoutes,
} from "../shell/viewRegistry";
import type { StreamingAccount, StreamingAccountsResponse } from "../streamingAccounts/queries";
import { AuthenticationSettingsView } from "./AuthenticationSettingsView";

const connectedAccount: StreamingAccount = {
  auth_error: null,
  auth_error_at: null,
  auth_state: "connected",
  created_at: "2026-05-01T09:00:00+00:00",
  display_name: "YouTube Music",
  id: 4,
  provider: "youtube_music",
  updated_at: "2026-05-02T09:00:00+00:00",
};

function renderWithProviders(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

function mockAccountFetch(accounts: StreamingAccountsResponse["accounts"]) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);

    if (url === "/api/streaming/accounts" && init?.method === undefined) {
      return jsonResponse({ accounts });
    }

    if (url === "/api/streaming/accounts" && init?.method === "POST") {
      return jsonResponse(connectedAccount);
    }

    if (url === "/api/streaming/accounts/4/auth" && init?.method === "PATCH") {
      return jsonResponse(connectedAccount);
    }

    throw new Error(`Unexpected fetch request: ${init?.method ?? "GET"} ${url}`);
  });
}

describe("AuthenticationSettingsView", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("registers the authentication settings route and nav item", () => {
    expect(settingsAuthenticationViewId).toBe("settings-authentication");
    expect(staticViewRoutes[settingsAuthenticationViewId]).toBe("/settings/authentication");
    expect(getViewPath(settingsAuthenticationViewId)).toBe("/settings/authentication");
    expect(getViewIdFromPath("/settings/authentication")).toBe(settingsAuthenticationViewId);
    expect(buildSettingsNavItems().map((item) => item.label)).toEqual([
      "General",
      "Authentication",
      "YouTube Music sync",
    ]);
  });

  it("submits no-account state with the expected POST body and clears the textarea", async () => {
    const browserHeaders = {
      authorization: "Bearer fresh",
      cookie: "SID=fresh",
    };
    const fetchMock = mockAccountFetch([]);

    renderWithProviders(<AuthenticationSettingsView />);

    expect(await screen.findByText("Not connected")).toBeInTheDocument();
    expect(screen.getByLabelText("Display name")).toHaveValue("YouTube Music");

    expect(screen.getByText("How to copy the cURL request")).toBeInTheDocument();
    expect(screen.getByText(/right-click and choose Copy > Copy as cURL/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("cURL request"), {
      target: {
        value: "curl 'https://music.youtube.com/youtubei/v1/browse' -H 'Authorization: Bearer fresh' -H 'Cookie: SID=fresh'",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/accounts", {
        body: JSON.stringify({
          display_name: "YouTube Music",
          browser_headers: browserHeaders,
        }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "POST",
      });
    });
    expect(await screen.findByText("YouTube Music authentication was saved.")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByLabelText("cURL request")).toHaveValue("");
    });
    expect(screen.getByRole("button", { name: "Configure playlists" })).toBeInTheDocument();
  });

  it("submits existing-account state with the expected PATCH body", async () => {
    const browserHeaders = {
      authorization: "Bearer refreshed",
      cookie: "SID=refreshed",
    };
    const fetchMock = mockAccountFetch([connectedAccount]);

    renderWithProviders(<AuthenticationSettingsView />);

    expect(await screen.findByText("Saved, not verified")).toBeInTheDocument();
    expect(screen.getByText(/next playlist sync will verify/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("cURL request"), {
      target: {
        value:
          "curl 'https://music.youtube.com/youtubei/v1/browse' " +
          "-H 'Authorization: Bearer refreshed' " +
          "-H 'Cookie: SID=refreshed'",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Refresh authentication" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/accounts/4/auth", {
        body: JSON.stringify({ browser_headers: browserHeaders }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "PATCH",
      });
    });
  });

  it("extracts request headers from a copied cURL command", async () => {
    const fetchMock = mockAccountFetch([connectedAccount]);

    renderWithProviders(<AuthenticationSettingsView />);

    expect(await screen.findByText("Saved, not verified")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("cURL request"), {
      target: {
        value:
          "curl 'https://music.youtube.com/youtubei/v1/browse?prettyPrint=false' " +
          "-H 'accept: */*' " +
          "-H 'authorization: SAPISIDHASH fresh_hash' " +
          "-H 'origin: https://music.youtube.com' " +
          "-b '__Secure-3PAPISID=fresh; SID=fresh' " +
          "--data-raw '{\"context\":{}}'",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Refresh authentication" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/accounts/4/auth", {
        body: JSON.stringify({
          browser_headers: {
            accept: "*/*",
            authorization: "SAPISIDHASH fresh_hash",
            origin: "https://music.youtube.com",
            cookie: "__Secure-3PAPISID=fresh; SID=fresh",
          },
        }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "PATCH",
      });
    });
  });

  it("extracts request headers from DevTools header text and drops pseudo headers", async () => {
    const fetchMock = mockAccountFetch([connectedAccount]);

    renderWithProviders(<AuthenticationSettingsView />);

    expect(await screen.findByText("Saved, not verified")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("cURL request"), {
      target: {
        value: [
          "Request URL: https://music.youtube.com/youtubei/v1/browse",
          "Request Method: POST",
          ":authority: music.youtube.com",
          "authorization: SAPISIDHASH copied_hash",
          "cookie: __Secure-3PAPISID=copied; SID=copied",
          "x-youtube-client-name: 67",
        ].join("\n"),
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Refresh authentication" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/accounts/4/auth", {
        body: JSON.stringify({
          browser_headers: {
            authorization: "SAPISIDHASH copied_hash",
            cookie: "__Secure-3PAPISID=copied; SID=copied",
            "x-youtube-client-name": "67",
          },
        }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "PATCH",
      });
    });
  });

  it("renders account authentication errors with their timestamp", async () => {
    mockAccountFetch([
      {
        ...connectedAccount,
        auth_error: "YouTube Music authentication failed: expired browser headers",
        auth_error_at: "2026-05-02T10:30:00+00:00",
        auth_state: "error",
      },
    ]);

    renderWithProviders(<AuthenticationSettingsView />);

    expect(await screen.findByText("Authentication needs attention")).toBeInTheDocument();
    expect(screen.getByText(/expired browser headers/)).toBeInTheDocument();
    expect(screen.getByText(/2026-05-02 10:30:00\+00:00/)).toBeInTheDocument();
  });

  it("does not render stored browser headers or auth blobs from the account response", async () => {
    mockAccountFetch([
      {
        ...connectedAccount,
        auth_token_blob: "SENTINEL_AUTH_BLOB",
        browser_headers: {
          Cookie: "SENTINEL_COOKIE",
        },
      } as StreamingAccount,
    ]);

    renderWithProviders(<AuthenticationSettingsView />);

    expect(await screen.findByText("Saved, not verified")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("SENTINEL_AUTH_BLOB");
    expect(document.body).not.toHaveTextContent("SENTINEL_COOKIE");
  });
});
