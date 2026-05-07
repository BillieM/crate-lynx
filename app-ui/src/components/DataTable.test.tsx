import { createColumnHelper, type RowSelectionState, type SortingState } from "@tanstack/react-table";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { useMemo, useState } from "react";
import { vi } from "vitest";

import { DataTable } from "./DataTable";

type TestTrack = {
  album: string;
  id: string;
  status: "linked" | "unlinked";
  title: string;
};

const tracks: TestTrack[] = [
  { album: "Moon Safari", id: "1", status: "linked", title: "La femme d'argent" },
  { album: "Discovery", id: "2", status: "unlinked", title: "Digital Love" },
  { album: "Settle", id: "3", status: "unlinked", title: "Latch" },
];

const columnHelper = createColumnHelper<TestTrack>();
const columns = [
  columnHelper.accessor("title", {
    cell: (info) => info.getValue(),
    header: "Title",
  }),
  columnHelper.accessor("album", {
    cell: (info) => info.getValue(),
    header: "Album",
    meta: {
      hideBelow: "md",
      widthClass: "w-48",
    },
  }),
  columnHelper.accessor("status", {
    cell: (info) => info.getValue(),
    header: "Status",
  }),
];

function TestDataTable({
  data = tracks,
  onActivate = vi.fn(),
}: {
  data?: TestTrack[];
  onActivate?: (track: TestTrack) => void;
}) {
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [sorting, setSorting] = useState<SortingState>([]);
  const hasUnlinkedSelection = data.some((track) => rowSelection[track.id] && track.status === "unlinked");

  return (
    <DataTable
      bulkActionSlot={
        <button disabled={!hasUnlinkedSelection} type="button">
          Re-match
        </button>
      }
      columns={columns}
      data={data}
      rowId={(track) => track.id}
      rowSelection={rowSelection}
      sorting={sorting}
      stickyHeader
      onActivate={onActivate}
      onRowSelectionChange={setRowSelection}
      onSortingChange={setSorting}
    />
  );
}

function FilterableDataTable() {
  const [filter, setFilter] = useState("");
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [sorting, setSorting] = useState<SortingState>([]);
  const filteredTracks = useMemo(
    () => tracks.filter((track) => track.title.toLowerCase().includes(filter.toLowerCase())),
    [filter],
  );

  function updateFilter(value: string) {
    setFilter(value);
    setRowSelection({});
  }

  return (
    <>
      <label htmlFor="track-filter">Filter</label>
      <input id="track-filter" value={filter} onChange={(event) => updateFilter(event.currentTarget.value)} />
      <DataTable
        columns={columns}
        data={filteredTracks}
        rowId={(track) => track.id}
        rowSelection={rowSelection}
        sorting={sorting}
        onActivate={vi.fn()}
        onRowSelectionChange={setRowSelection}
        onSortingChange={setSorting}
      />
    </>
  );
}

describe("DataTable", () => {
  it("selects, deselects, clears, and select-all toggles visible rows", () => {
    render(<TestDataTable />);

    expect(screen.queryByText("0 rows selected")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: "Select row 1" }));

    expect(screen.getByText("1 row selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select row 1" })).toBeChecked();

    fireEvent.click(screen.getByRole("checkbox", { name: "Select row 1" }));

    expect(screen.queryByText("1 row selected")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select row 1" })).not.toBeChecked();

    fireEvent.click(screen.getByRole("checkbox", { name: "Select all visible rows" }));

    expect(screen.getByText("3 rows selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select row 2" })).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));

    expect(screen.queryByText("3 rows selected")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select row 2" })).not.toBeChecked();
  });

  it("supports sorting and keeps responsive column metadata on cells", () => {
    render(<TestDataTable />);

    fireEvent.click(screen.getByRole("button", { name: /Title/ }));

    const rows = screen.getAllByRole("row");
    expect(within(rows[1]).getByText("Digital Love")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Album/ })).toHaveClass("hidden", "md:table-cell", "w-48");
  });

  it("supports keyboard selection, row activation, and arrow focus movement", () => {
    const onActivate = vi.fn();
    render(<TestDataTable onActivate={onActivate} />);

    const firstBodyRow = screen.getAllByRole("row")[1];
    const secondBodyRow = screen.getAllByRole("row")[2];

    firstBodyRow.focus();
    fireEvent.keyDown(firstBodyRow, { key: " " });
    expect(screen.getByRole("checkbox", { name: "Select row 1" })).toBeChecked();

    fireEvent.keyDown(firstBodyRow, { key: "ArrowDown" });
    expect(secondBodyRow).toHaveFocus();

    fireEvent.keyDown(secondBodyRow, { key: "Enter" });
    expect(onActivate).toHaveBeenCalledWith(tracks[1]);
  });

  it("uses shift-click to select a visible row range", () => {
    render(<TestDataTable />);

    fireEvent.click(screen.getByRole("checkbox", { name: "Select row 1" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select row 3" }), { shiftKey: true });

    expect(screen.getByText("3 rows selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select row 2" })).toBeChecked();
  });

  it("lets callers enforce bulk action enablement from lifted selection state", () => {
    render(<TestDataTable />);

    fireEvent.click(screen.getByRole("checkbox", { name: "Select row 1" }));

    expect(screen.getByRole("button", { name: "Re-match" })).toBeDisabled();

    fireEvent.click(screen.getByRole("checkbox", { name: "Select row 2" }));

    expect(screen.getByRole("button", { name: "Re-match" })).toBeEnabled();
  });

  it("supports caller-driven selection clearing when filters change", () => {
    render(<FilterableDataTable />);

    fireEvent.click(screen.getByRole("checkbox", { name: "Select row 2" }));

    expect(screen.getByText("1 row selected")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Filter"), { target: { value: "Latch" } });

    expect(screen.queryByText("1 row selected")).not.toBeInTheDocument();
    expect(screen.getByText("Latch")).toBeInTheDocument();
  });
});
