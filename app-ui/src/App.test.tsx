import { render } from "@testing-library/react";
import App, { asRgb, getProgressColor, lerp, mixColors } from "./App";

describe("App", () => {
  it("renders the fixed-height shell container", () => {
    const { container } = render(<App />);

    expect(container.firstChild).toHaveClass("text-ctp-text");

    const shell = container.querySelector(".bg-ctp-base");

    expect(shell).toHaveClass(
      "flex",
      "h-[640px]",
      "flex-row",
      "overflow-hidden",
      "rounded-[12px]",
      "border",
      "border-ctp-surface0",
    );
  });

  it("interpolates scalar values with rounding", () => {
    expect(lerp(10, 20, 0.45)).toBe(15);
  });

  it("mixes RGB colors channel by channel", () => {
    expect(
      mixColors(
        { red: 10, green: 20, blue: 30 },
        { red: 40, green: 80, blue: 120 },
        0.5,
      ),
    ).toEqual({ red: 25, green: 50, blue: 75 });
  });

  it("maps progress percentages onto the Catppuccin gradient", () => {
    expect(getProgressColor(-10)).toEqual({ red: 108, green: 112, blue: 134 });
    expect(getProgressColor(50)).toEqual({ red: 249, green: 226, blue: 175 });
    expect(getProgressColor(100)).toEqual({ red: 166, green: 227, blue: 161 });
  });

  it("formats rgba strings with optional alpha", () => {
    expect(asRgb({ red: 1, green: 2, blue: 3 })).toBe("rgba(1, 2, 3, 1)");
    expect(asRgb({ red: 1, green: 2, blue: 3 }, 0.4)).toBe("rgba(1, 2, 3, 0.4)");
  });
});
