import type { PlaylistTrackFilter } from "./filterTracks";
import { FilterChipGroup, type FilterChipOption } from "../../components/FilterChipGroup";

type FilterChipsProps = {
  activeFilter: PlaylistTrackFilter;
  counts?: Partial<Record<PlaylistTrackFilter, number>>;
  onFilterChange: (filter: PlaylistTrackFilter) => void;
};

const filterChips = [
  {
    label: "All",
    tone: "all",
    value: "all",
  },
  {
    label: "Linked",
    tone: "linked",
    value: "linked",
  },
  {
    label: "Pending",
    tone: "pending",
    value: "pending",
  },
  {
    label: "Unlinked",
    tone: "unlinked",
    value: "unlinked",
  },
] satisfies FilterChipOption<PlaylistTrackFilter>[];

export function FilterChips({ activeFilter, counts, onFilterChange }: FilterChipsProps) {
  const options = filterChips.map((chip) => ({
    ...chip,
    count: counts?.[chip.value],
  }));

  return (
    <FilterChipGroup
      activeValue={activeFilter}
      ariaLabel="Track status filters"
      onValueChange={onFilterChange}
      options={options}
    />
  );
}
