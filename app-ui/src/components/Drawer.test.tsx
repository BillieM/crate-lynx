import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";

import { Drawer } from "./Drawer";

function DrawerHarness() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open details
      </button>
      <Drawer open={open} title="Track detail" onClose={() => setOpen(false)}>
        <button type="button">First action</button>
        <button type="button">Last action</button>
      </Drawer>
    </>
  );
}

describe("Drawer", () => {
  it("opens as an accessible dialog and closes from the close control", () => {
    render(<DrawerHarness />);
    const opener = screen.getByRole("button", { name: "Open details" });

    opener.focus();
    fireEvent.click(opener);

    expect(screen.getByRole("dialog", { name: "Track detail" })).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Close drawer" })[1]);

    expect(screen.queryByRole("dialog", { name: "Track detail" })).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("closes on Escape and returns focus to the invoker", () => {
    render(<DrawerHarness />);
    const opener = screen.getByRole("button", { name: "Open details" });

    opener.focus();
    fireEvent.click(opener);
    fireEvent.keyDown(screen.getByRole("dialog", { name: "Track detail" }), { key: "Escape" });

    expect(screen.queryByRole("dialog", { name: "Track detail" })).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("keeps Tab focus inside the drawer", () => {
    render(<DrawerHarness />);

    fireEvent.click(screen.getByRole("button", { name: "Open details" }));
    const dialog = screen.getByRole("dialog", { name: "Track detail" });
    const closeButton = screen.getAllByRole("button", { name: "Close drawer" })[1];
    const lastButton = screen.getByRole("button", { name: "Last action" });

    closeButton.focus();
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });

    expect(lastButton).toHaveFocus();
  });
});
