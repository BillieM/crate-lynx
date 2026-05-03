import type { PlaylistTrackFilter } from "./filterTracks";

type FilterChipsProps = {
  activeFilter: PlaylistTrackFilter;
  counts?: Partial<Record<PlaylistTrackFilter, number>>;
  onFilterChange: (filter: PlaylistTrackFilter) => void;
};

type FilterChipConfig = {
  filter: PlaylistTrackFilter;
  label: string;
  selectedClassName: string;
};

const filterChips: FilterChipConfig[] = [
  {
    filter: "all",
    label: "All",
    selectedClassName:
      "border-ctp-blue bg-ctp-blue/18 text-ctp-blue shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-ctp-blue)_12%,transparent)]",
  },
  {
    filter: "linked",
    label: "Linked",
    selectedClassName:
      "border-ctp-green bg-ctp-green/18 text-ctp-green shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-ctp-green)_12%,transparent)]",
  },
  {
    filter: "pending",
    label: "Pending",
    selectedClassName:
      "border-ctp-yellow bg-ctp-yellow/18 text-ctp-yellow shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-ctp-yellow)_12%,transparent)]",
  },
  {
    filter: "unlinked",
    label: "Unlinked",
    selectedClassName:
      "border-ctp-red bg-ctp-red/18 text-ctp-red shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-ctp-red)_12%,transparent)]",
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
                ? chip.selectedClassName
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
