import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

describe("App", () => {
  it("redirects the root route to maintenance inside the shared shell", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", {
        name: /keep ingestion and recovery moving\./i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", {
        name: /sidebar/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("searchbox", {
        name: /global search/i,
      }),
    ).toBeInTheDocument();
  });

  it("keeps the shell visible on the youtube music route", () => {
    render(
      <MemoryRouter initialEntries={["/youtube-music"]}>
        <App />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", {
        name: /review sync status and playlist linkage\./i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: /^local library$/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: /recent activity/i,
      }),
    ).toBeInTheDocument();
  });

  it("renders the local library route content within the shared main area", () => {
    render(
      <MemoryRouter initialEntries={["/local-library"]}>
        <App />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", {
        name: /manage your source-of-truth music archive\./i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/main content area/i)).toBeInTheDocument();
  });
});
