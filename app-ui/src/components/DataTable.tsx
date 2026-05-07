import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  type ColumnDef,
  type OnChangeFn,
  type RowSelectionState,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { type KeyboardEvent, type ReactNode, useMemo, useRef } from "react";

import { controlClasses, surfaceClasses, textClasses } from "../styles/componentClasses";

declare module "@tanstack/react-table" {
  // TanStack requires these generic names for ColumnMeta augmentation.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData, TValue> {
    align?: "start" | "end";
    hideBelow?: "sm" | "md" | "lg";
    widthClass?: string;
  }
}

type Density = "compact";

// Heterogeneous table columns naturally carry different TValue generics.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type DataTableColumn<TRow> = ColumnDef<TRow, any>;

export type DataTableProps<TRow> = {
  bulkActionSlot?: ReactNode;
  columns: Array<DataTableColumn<TRow>>;
  data: TRow[];
  density?: Density;
  onActivate?: (row: TRow) => void;
  onRowSelectionChange: OnChangeFn<RowSelectionState>;
  onSortingChange: OnChangeFn<SortingState>;
  rowId: (row: TRow) => string;
  rowSelection: RowSelectionState;
  sorting: SortingState;
  stickyHeader?: boolean;
};

type BulkActionBarProps = {
  children?: ReactNode;
  onClearSelection: () => void;
  selectedCount: number;
};

const hideBelowClasses = {
  lg: "hidden lg:table-cell",
  md: "hidden md:table-cell",
  sm: "hidden sm:table-cell",
};

const densityClasses = {
  compact: {
    cell: "px-3 py-2",
    row: "min-h-10",
  },
};

function getRowSelectionState(rowIds: string[], rowSelection: RowSelectionState): "all" | "some" | "none" {
  const selectedCount = rowIds.filter((rowId) => rowSelection[rowId]).length;

  if (selectedCount === 0) {
    return "none";
  }

  return selectedCount === rowIds.length ? "all" : "some";
}

export function BulkActionBar({ children, onClearSelection, selectedCount }: BulkActionBarProps) {
  if (selectedCount === 0) {
    return null;
  }

  return (
    <div
      aria-live="polite"
      className={`${surfaceClasses.insetPanel} flex flex-wrap items-center justify-between gap-3 px-3 py-2`}
    >
      <p className={`${textClasses.status} tabular-nums text-ctp-text`}>
        {selectedCount} {selectedCount === 1 ? "row" : "rows"} selected
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {children}
        <button
          className={`${controlClasses.actionButton} border-ctp-surface1 bg-ctp-surface0 text-ctp-text hover:bg-ctp-surface1`}
          type="button"
          onClick={onClearSelection}
        >
          Clear selection
        </button>
      </div>
    </div>
  );
}

export function DataTable<TRow>({
  bulkActionSlot,
  columns,
  data,
  density = "compact",
  onActivate,
  onRowSelectionChange,
  onSortingChange,
  rowId,
  rowSelection,
  sorting,
  stickyHeader = false,
}: DataTableProps<TRow>) {
  const table = useReactTable({
    columns,
    data,
    enableRowSelection: true,
    getCoreRowModel: getCoreRowModel(),
    getRowId: rowId,
    getSortedRowModel: getSortedRowModel(),
    onRowSelectionChange,
    onSortingChange,
    state: {
      rowSelection,
      sorting,
    },
  });
  const lastSelectedIndexRef = useRef<number | null>(null);
  const visibleRows = table.getRowModel().rows;
  const visibleRowIds = useMemo(() => visibleRows.map((row) => row.id), [visibleRows]);
  const selectedVisibleCount = visibleRowIds.filter((rowIdValue) => rowSelection[rowIdValue]).length;
  const headerSelectionState = getRowSelectionState(visibleRowIds, rowSelection);
  const tableDensity = densityClasses[density];

  function setRowSelected(rowIndex: number, checked: boolean, shiftKey = false) {
    const nextSelection = { ...rowSelection };
    const lastSelectedIndex = lastSelectedIndexRef.current;

    if (shiftKey && lastSelectedIndex !== null) {
      const rangeStart = Math.min(lastSelectedIndex, rowIndex);
      const rangeEnd = Math.max(lastSelectedIndex, rowIndex);

      for (let index = rangeStart; index <= rangeEnd; index += 1) {
        const selectedRowId = visibleRows[index]?.id;

        if (selectedRowId) {
          nextSelection[selectedRowId] = checked;
        }
      }
    } else {
      const selectedRowId = visibleRows[rowIndex]?.id;

      if (selectedRowId) {
        nextSelection[selectedRowId] = checked;
      }
    }

    lastSelectedIndexRef.current = rowIndex;
    onRowSelectionChange(nextSelection);
  }

  function clearSelection() {
    onRowSelectionChange({});
  }

  function toggleAllVisible(checked: boolean) {
    onRowSelectionChange((currentSelection) => {
      const nextSelection = { ...currentSelection };

      for (const visibleRowId of visibleRowIds) {
        nextSelection[visibleRowId] = checked;
      }

      return nextSelection;
    });
  }

  function toggleRowFromKeyboard(rowIndex: number) {
    const selectedRowId = visibleRows[rowIndex]?.id;

    if (!selectedRowId) {
      return;
    }

    setRowSelected(rowIndex, !rowSelection[selectedRowId]);
  }

  function focusSiblingRow(currentTarget: HTMLTableRowElement, direction: "next" | "previous") {
    const rows = Array.from(currentTarget.closest("tbody")?.querySelectorAll<HTMLTableRowElement>("tr[data-row-id]") ?? []);
    const currentIndex = rows.indexOf(currentTarget);
    const nextIndex = direction === "next" ? currentIndex + 1 : currentIndex - 1;

    rows[nextIndex]?.focus();
  }

  function handleRowKeyDown(event: KeyboardEvent<HTMLTableRowElement>, rowIndex: number, rowOriginal: TRow) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      focusSiblingRow(event.currentTarget, "next");
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      focusSiblingRow(event.currentTarget, "previous");
    }

    if (event.key === " ") {
      event.preventDefault();
      toggleRowFromKeyboard(rowIndex);
    }

    if (event.key === "Enter" && onActivate) {
      event.preventDefault();
      onActivate(rowOriginal);
    }
  }

  return (
    <div className="space-y-2">
      <BulkActionBar selectedCount={selectedVisibleCount} onClearSelection={clearSelection}>
        {bulkActionSlot}
      </BulkActionBar>
      <div
        className={`${surfaceClasses.panelRadius} overflow-x-auto border border-ctp-surface1/80 bg-ctp-mantle/75 shadow-sm shadow-ctp-crust/20`}
      >
        <table className="min-w-full border-collapse text-left">
          <thead className={stickyHeader ? "sticky top-0 z-10" : ""}>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className="border-b border-ctp-surface1 bg-ctp-surface0/95">
                <th className="w-10 px-3 py-2 text-left">
                  <input
                    aria-label="Select all visible rows"
                    checked={headerSelectionState === "all"}
                    className="h-4 w-4 accent-ctp-mauve"
                    ref={(input) => {
                      if (input) {
                        input.indeterminate = headerSelectionState === "some";
                      }
                    }}
                    type="checkbox"
                    onChange={(event) => toggleAllVisible(event.currentTarget.checked)}
                  />
                </th>
                {headerGroup.headers.map((header) => {
                  const meta = header.column.columnDef.meta;
                  const alignClass = meta?.align === "end" ? "text-right" : "text-left";
                  const hideClass = meta?.hideBelow ? hideBelowClasses[meta.hideBelow] : "";
                  const widthClass = meta?.widthClass ?? "";
                  const sortDirection = header.column.getIsSorted();

                  return (
                    <th
                      key={header.id}
                      className={`${tableDensity.cell} ${alignClass} ${hideClass} ${widthClass} ${textClasses.microEyebrow} text-ctp-subtext0`}
                      scope="col"
                    >
                      {header.isPlaceholder ? null : header.column.getCanSort() ? (
                        <button
                          className={`inline-flex items-center gap-1 ${alignClass === "text-right" ? "justify-end" : "justify-start"}`}
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          <span aria-hidden="true" className="text-ctp-overlay0">
                            {sortDirection === "asc" ? "↑" : sortDirection === "desc" ? "↓" : "↕"}
                          </span>
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {visibleRows.map((row, rowIndex) => (
              <tr
                key={row.id}
                className={`${tableDensity.row} border-b border-ctp-surface0/80 outline-none transition-colors last:border-b-0 hover:bg-ctp-surface0/70 focus-visible:bg-ctp-surface0 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ctp-mauve`}
                data-row-id={row.id}
                tabIndex={0}
                onKeyDown={(event) => handleRowKeyDown(event, rowIndex, row.original)}
              >
                <td className="w-10 px-3 py-2">
                  <input
                    aria-label={`Select row ${rowIndex + 1}`}
                    checked={row.getIsSelected()}
                    className="h-4 w-4 accent-ctp-mauve"
                    type="checkbox"
                    onChange={(event) => {
                      const nativeEvent = event.nativeEvent;
                      const shiftKey = "shiftKey" in nativeEvent ? Boolean(nativeEvent.shiftKey) : false;

                      setRowSelected(rowIndex, event.currentTarget.checked, shiftKey);
                    }}
                    onClick={(event) => event.stopPropagation()}
                  />
                </td>
                {row.getVisibleCells().map((cell) => {
                  const meta = cell.column.columnDef.meta;
                  const alignClass = meta?.align === "end" ? "text-right" : "text-left";
                  const hideClass = meta?.hideBelow ? hideBelowClasses[meta.hideBelow] : "";
                  const widthClass = meta?.widthClass ?? "";

                  return (
                    <td
                      key={cell.id}
                      className={`${tableDensity.cell} ${alignClass} ${hideClass} ${widthClass} min-w-0 text-[12px] text-ctp-text`}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
