import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

describe("App", () => {
  it("redirects the root route to maintenance", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", {
        name: /^maintenance$/i,
      }),
    ).toBeInTheDocument();
  });

  it("renders the youtube music route", () => {
    render(
      <MemoryRouter initialEntries={["/youtube-music"]}>
        <App />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", {
        name: /^youtube music$/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: /^local library$/i,
      }),
    ).toBeInTheDocument();
  });

  it("renders the local library route", () => {
    render(
      <MemoryRouter initialEntries={["/local-library"]}>
        <App />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", {
        name: /^local library$/i,
      }),
    ).toBeInTheDocument();
  });
});
