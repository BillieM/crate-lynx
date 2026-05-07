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
      Authorization: "Bearer fresh",
      Cookie: "SID=fresh",
    };
    const fetchMock = mockAccountFetch([]);

    renderWithProviders(<AuthenticationSettingsView />);

    expect(await screen.findByText("Not connected")).toBeInTheDocument();
    expect(screen.getByLabelText("Display name")).toHaveValue("YouTube Music");

    fireEvent.change(screen.getByLabelText("Browser headers"), {
      target: {
        value: JSON.stringify(browserHeaders),
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
      expect(screen.getByLabelText("Browser headers")).toHaveValue("");
    });
    expect(screen.getByRole("button", { name: "Configure playlists" })).toBeInTheDocument();
  });

  it("submits existing-account state with the expected PATCH body", async () => {
    const browserHeaders = {
      Authorization: "Bearer refreshed",
      Cookie: "SID=refreshed",
    };
    const fetchMock = mockAccountFetch([connectedAccount]);

    renderWithProviders(<AuthenticationSettingsView />);

    expect(await screen.findByText("Connected")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Browser headers"), {
      target: {
        value: JSON.stringify(browserHeaders),
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

    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("SENTINEL_AUTH_BLOB");
    expect(document.body).not.toHaveTextContent("SENTINEL_COOKIE");
  });
});
