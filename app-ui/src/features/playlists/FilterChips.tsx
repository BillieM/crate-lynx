import type { PlaylistTrackFilter } from "./filterTracks";
import { selectedFilterChipClasses } from "../../styles/toneClasses";

type FilterChipsProps = {
  activeFilter: PlaylistTrackFilter;
  counts?: Partial<Record<PlaylistTrackFilter, number>>;
  onFilterChange: (filter: PlaylistTrackFilter) => void;
};

type FilterChipConfig = {
  filter: PlaylistTrackFilter;
  label: string;
};

const filterChips: FilterChipConfig[] = [
  {
    filter: "all",
    label: "All",
  },
  {
    filter: "linked",
    label: "Linked",
  },
  {
    filter: "pending",
    label: "Pending",
  },
  {
    filter: "unlinked",
    label: "Unlinked",
  },
];

export function FilterChips({ activeFilter, counts, onFilterChange }: FilterChipsProps) {
  return (
    <div aria-label="Track status filters" className="flex flex-wrap items-center gap-2" role="group">
      {filterChips.map((chip) => {
        const isSelected = activeFilter === chip.filter;
        const count = counts?.[chip.filter];

        return (
          <button
            aria-pressed={isSelected}
            className={`inline-flex min-h-10 items-center gap-2 rounded-[999px] border px-4 text-[13px] font-semibold transition-colors ${
              isSelected
                ? selectedFilterChipClasses[chip.filter]
                : "border-ctp-surface1 bg-ctp-surface0 text-ctp-subtext0 hover:border-ctp-overlay0 hover:bg-ctp-surface1 hover:text-ctp-text"
            }`}
            key={chip.filter}
            onClick={() => onFilterChange(chip.filter)}
            type="button"
          >
            <span>{chip.label}</span>
            {count !== undefined ? (
              <span className="min-w-6 rounded-[999px] bg-ctp-mantle px-2 py-0.5 text-center text-[11px] tabular-nums text-ctp-subtext0 ring-1 ring-inset ring-ctp-surface1">
                {count}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
