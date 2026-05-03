import { render, screen } from "@testing-library/react";
import App from "./App";

describe("App", () => {
  it("renders the scaffold heading", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", {
        name: /frontend scaffold ready for the playlist ui/i,
      }),
    ).toBeInTheDocument();
  });

  it("renders the Tailwind setup callout", () => {
    render(<App />);

    expect(screen.getByText(/tailwind v4/i)).toBeInTheDocument();
    expect(
      screen.getByText(/^the palette is available directly through `ctp` colour tokens\.$/i),
    ).toBeInTheDocument();
  });
});
