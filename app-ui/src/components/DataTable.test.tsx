import { createColumnHelper, type ColumnFiltersState, type RowSelectionState, type SortingState } from "@tanstack/react-table";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
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
    meta: {
      sticky: "left",
    },
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
  columnHelper.display({
    cell: () => <button type="button">Inspect</button>,
    header: "Actions",
    id: "actions",
    meta: {
      sticky: "right",
    },
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

function NonSelectableDataTable({ onActivate = vi.fn() }: { onActivate?: (track: TestTrack) => void }) {
  const [sorting, setSorting] = useState<SortingState>([]);

  return (
    <DataTable
      bulkActionSlot={<button type="button">Re-match</button>}
      columns={columns}
      data={tracks}
      enableRowSelection={false}
      rowId={(track) => track.id}
      sorting={sorting}
      stickyHeader
      onActivate={onActivate}
      onSortingChange={setSorting}
    />
  );
}

function StaticDataTable() {
  const [sorting, setSorting] = useState<SortingState>([]);

  return (
    <DataTable
      columns={columns}
      data={tracks}
      enableRowSelection={false}
      rowId={(track) => track.id}
      sorting={sorting}
      onSortingChange={setSorting}
    />
  );
}

function FilterableDataTable() {
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [sorting, setSorting] = useState<SortingState>([]);
  const activeFilter = (columnFilters[0]?.value as TestTrack["status"] | undefined) ?? "all";

  function updateFilter(value: string) {
    setColumnFilters(value === "all" ? [] : [{ id: "status", value }]);
  }

  return (
    <>
      <label htmlFor="track-filter">Filter</label>
      <select id="track-filter" value={activeFilter} onChange={(event) => updateFilter(event.currentTarget.value)}>
        <option value="all">All</option>
        <option value="linked">Linked</option>
        <option value="unlinked">Unlinked</option>
      </select>
      <DataTable
        columnFilters={columnFilters}
        columns={columns}
        data={tracks}
        headerSlot={({ filteredRowCount, totalRowCount }) => (
          <p>
            Showing {filteredRowCount} of {totalRowCount} tracks
          </p>
        )}
        rowId={(track) => track.id}
        rowSelection={rowSelection}
        sorting={sorting}
        onActivate={vi.fn()}
        onColumnFiltersChange={setColumnFilters}
        onRowSelectionChange={setRowSelection}
        onSortingChange={setSorting}
      />
    </>
  );
}

describe("DataTable", () => {
  it("defaults to selectable rendering", () => {
    render(<TestDataTable />);

    expect(screen.getByRole("checkbox", { name: "Select all visible rows" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select row 1" })).toBeInTheDocument();
  });

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

    expect(screen.getByRole("columnheader", { name: /Title/ })).toHaveAttribute("aria-sort", "none");

    fireEvent.click(screen.getByRole("button", { name: /Title/ }));

    const rows = screen.getAllByRole("row");
    expect(within(rows[1]).getByText("Digital Love")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Title/ })).toHaveAttribute("aria-sort", "ascending");
    expect(screen.getByRole("columnheader", { name: /Album/ })).toHaveClass("hidden", "md:table-cell", "w-48");

    fireEvent.click(screen.getByRole("button", { name: /Title/ }));

    expect(screen.getByRole("columnheader", { name: /Title/ })).toHaveAttribute("aria-sort", "descending");
    expect(screen.getByRole("columnheader", { name: /Actions/ })).not.toHaveAttribute("aria-sort");
    expect(screen.getByRole("columnheader", { name: /Title/ })).toHaveClass("sticky", "left-10");
    expect(screen.getByRole("columnheader", { name: /Actions/ })).toHaveClass("sticky", "right-0");
  });

  it("supports keyboard selection, row activation, and arrow focus movement", () => {
    const onActivate = vi.fn();
    render(<TestDataTable onActivate={onActivate} />);

    const firstBodyRow = screen.getAllByRole("row")[1];
    const secondBodyRow = screen.getAllByRole("row")[2];
    const thirdBodyRow = screen.getAllByRole("row")[3];

    expect(firstBodyRow).toHaveAttribute("tabindex", "0");
    expect(secondBodyRow).toHaveAttribute("tabindex", "-1");

    firstBodyRow.focus();
    fireEvent.keyDown(firstBodyRow, { key: " " });
    expect(screen.getByRole("checkbox", { name: "Select row 1" })).toBeChecked();

    fireEvent.keyDown(firstBodyRow, { key: "ArrowDown" });
    expect(secondBodyRow).toHaveFocus();
    expect(secondBodyRow).toHaveAttribute("tabindex", "0");
    expect(firstBodyRow).toHaveAttribute("tabindex", "-1");

    fireEvent.keyDown(secondBodyRow, { key: "End" });
    expect(thirdBodyRow).toHaveFocus();

    fireEvent.keyDown(thirdBodyRow, { key: "Home" });
    expect(firstBodyRow).toHaveFocus();

    fireEvent.keyDown(firstBodyRow, { key: "Enter" });
    expect(onActivate).toHaveBeenCalledWith(tracks[0]);
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

  it("renders without selection UI or keyboard row selection when row selection is disabled", () => {
    const onActivate = vi.fn();
    render(<NonSelectableDataTable onActivate={onActivate} />);

    expect(screen.queryByRole("checkbox", { name: "Select all visible rows" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Select row 1" })).not.toBeInTheDocument();
    expect(screen.queryByText(/rows? selected/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear selection" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Re-match" })).not.toBeInTheDocument();

    const firstBodyRow = screen.getAllByRole("row")[1];
    const secondBodyRow = screen.getAllByRole("row")[2];

    firstBodyRow.focus();
    fireEvent.keyDown(firstBodyRow, { key: " " });

    expect(screen.queryByText(/rows? selected/)).not.toBeInTheDocument();

    fireEvent.keyDown(firstBodyRow, { key: "ArrowDown" });
    expect(secondBodyRow).toHaveFocus();

    fireEvent.keyDown(secondBodyRow, { key: "Enter" });
    expect(onActivate).toHaveBeenCalledWith(tracks[1]);
  });

  it("does not add row tab stops when rows have no row-level action", () => {
    render(<StaticDataTable />);

    expect(screen.getAllByRole("row")[1]).not.toHaveAttribute("tabindex");
  });

  it("supports controlled column filters, header counts, and selection clearing when filters change", () => {
    render(<FilterableDataTable />);

    expect(screen.getByText("Showing 3 of 3 tracks")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: "Select row 2" }));

    expect(screen.getByText("1 row selected")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Filter"), { target: { value: "unlinked" } });

    expect(screen.queryByText("1 row selected")).not.toBeInTheDocument();
    expect(screen.getByText("Showing 2 of 3 tracks")).toBeInTheDocument();
    expect(screen.queryByText("La femme d'argent")).not.toBeInTheDocument();
    expect(screen.getByText("Digital Love")).toBeInTheDocument();
    expect(screen.getByText("Latch")).toBeInTheDocument();
  });

  it("activates rows on plain cell clicks and ignores interactive row targets", () => {
    const onActivate = vi.fn();
    render(<TestDataTable onActivate={onActivate} />);

    const firstBodyRow = screen.getAllByRole("row")[1];

    fireEvent.click(within(firstBodyRow).getByText("La femme d'argent"));

    expect(onActivate).toHaveBeenCalledWith(tracks[0]);

    onActivate.mockClear();
    fireEvent.click(within(firstBodyRow).getByRole("checkbox", { name: "Select row 1" }));

    expect(onActivate).not.toHaveBeenCalled();

    fireEvent.click(within(firstBodyRow).getByRole("button", { name: "Inspect" }));

    expect(onActivate).not.toHaveBeenCalled();
  });

  it("does not render a header slot wrapper when headerSlot is omitted", () => {
    const { container } = render(<TestDataTable />);

    expect(container.firstElementChild?.children).toHaveLength(1);
    expect(screen.queryByText(/Showing \d+ of \d+ tracks/)).not.toBeInTheDocument();
  });
});
