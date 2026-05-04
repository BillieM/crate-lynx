import { Clock3, Link2, Music2, RotateCcw, SlidersHorizontal, Unlink } from "lucide-react";
import { useState } from "react";
import { ActionButton } from "../../components/ActionButton";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { FilterChipGroup, type FilterChipOption } from "../../components/FilterChipGroup";
import { controlClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";

type LibraryLinkStatusFilter = "all" | "linked" | "pending" | "unlinked";
type LibraryMatchMethodFilter = "all" | "isrc" | "tag" | "acoustic" | "manual";
type LibraryFileStatusFilter = "all" | "available" | "missing" | "beets_failed";

type LibraryStat = {
  description: string;
  icon: typeof Music2;
  label: string;
  toneClass: string;
  value: number;
};

const libraryStats = [
  {
    description: "All imported local tracks",
    icon: Music2,
    label: "Total",
    toneClass: "bg-ctp-blue/18 text-ctp-blue ring-ctp-blue/30",
    value: 312,
  },
  {
    description: "Tracks with approved streaming links",
    icon: Link2,
    label: "Linked",
    toneClass: "bg-ctp-green/18 text-ctp-green ring-ctp-green/30",
    value: 244,
  },
  {
    description: "Tracks with suggested links awaiting review",
    icon: Clock3,
    label: "Pending",
    toneClass: "bg-ctp-yellow/18 text-ctp-yellow ring-ctp-yellow/30",
    value: 43,
  },
  {
    description: "Tracks without a usable match",
    icon: Unlink,
    label: "Unlinked",
    toneClass: "bg-ctp-red/18 text-ctp-red ring-ctp-red/30",
    value: 25,
  },
] satisfies LibraryStat[];

const linkStatusFilters = [
  {
    count: 312,
    label: "All",
    tone: "all",
    value: "all",
  },
  {
    count: 244,
    label: "Linked",
    tone: "linked",
    value: "linked",
  },
  {
    count: 43,
    label: "Pending",
    tone: "pending",
    value: "pending",
  },
  {
    count: 25,
    label: "Unlinked",
    tone: "unlinked",
    value: "unlinked",
  },
] satisfies FilterChipOption<LibraryLinkStatusFilter>[];

const matchMethodFilters = [
  { label: "All methods", value: "all" },
  { label: "ISRC", value: "isrc" },
  { label: "Tag", value: "tag" },
  { label: "Acoustic", value: "acoustic" },
  { label: "Manual", value: "manual" },
] satisfies { label: string; value: LibraryMatchMethodFilter }[];

const fileStatusFilters = [
  { label: "All files", value: "all" },
  { label: "Available locally", value: "available" },
  { label: "Missing locally", value: "missing" },
  { label: "Beets failed", value: "beets_failed" },
] satisfies { label: string; value: LibraryFileStatusFilter }[];

function LibraryStatCard({ stat }: { stat: LibraryStat }) {
  const Icon = stat.icon;

  return (
    <section className={`${surfaceClasses.compactCard} min-h-28`} aria-label={`${stat.label} tracks`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className={`${textClasses.microEyebrow} text-ctp-subtext0`}>{stat.label}</p>
          <p className="mt-2 text-[28px] font-semibold leading-none tabular-nums text-ctp-text">
            {stat.value.toLocaleString()}
          </p>
        </div>
        <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-[8px] ring-1 ring-inset ${stat.toneClass}`}>
          <Icon aria-hidden="true" className="h-[18px] w-[18px]" strokeWidth={1.8} />
        </div>
      </div>
      <p className={`mt-3 ${textClasses.caption}`}>{stat.description}</p>
    </section>
  );
}

function LibrarySelectFilter<TValue extends string>({
  label,
  onValueChange,
  options,
  value,
}: {
  label: string;
  onValueChange: (value: TValue) => void;
  options: { label: string; value: TValue }[];
  value: TValue;
}) {
  return (
    <label className="grid min-w-[11rem] gap-1.5">
      <span className={textClasses.microEyebrow}>{label}</span>
      <select
        className={`${controlClasses.controlRadius} min-h-9 border border-ctp-surface1 bg-ctp-surface0 px-2.5 text-[12px] font-semibold text-ctp-text outline-none transition-colors hover:border-ctp-overlay0 focus:border-ctp-blue focus:ring-2 focus:ring-ctp-blue/20`}
        onChange={(event) => onValueChange(event.target.value as TValue)}
        value={value}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function LibraryFilterBar() {
  const [linkStatusFilter, setLinkStatusFilter] = useState<LibraryLinkStatusFilter>("all");
  const [matchMethodFilter, setMatchMethodFilter] = useState<LibraryMatchMethodFilter>("all");
  const [fileStatusFilter, setFileStatusFilter] = useState<LibraryFileStatusFilter>("all");
  const hasActiveFilters = linkStatusFilter !== "all" || matchMethodFilter !== "all" || fileStatusFilter !== "all";

  const resetFilters = () => {
    setLinkStatusFilter("all");
    setMatchMethodFilter("all");
    setFileStatusFilter("all");
  };

  return (
    <section
      aria-label="Library filters"
      className={`${surfaceClasses.compactCard} flex flex-wrap items-end justify-between gap-3`}
    >
      <div className="grid min-w-0 flex-1 gap-3">
        <div className="flex items-center gap-2 text-ctp-subtext0">
          <SlidersHorizontal aria-hidden="true" className="h-4 w-4" strokeWidth={1.8} />
          <h2 className={textClasses.label}>Library filters</h2>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="grid gap-1.5">
            <span className={textClasses.microEyebrow}>Link status</span>
            <FilterChipGroup
              activeValue={linkStatusFilter}
              ariaLabel="Library link status filters"
              density="compact"
              onValueChange={setLinkStatusFilter}
              options={linkStatusFilters}
            />
          </div>
          <LibrarySelectFilter
            label="Match method"
            onValueChange={setMatchMethodFilter}
            options={matchMethodFilters}
            value={matchMethodFilter}
          />
          <LibrarySelectFilter
            label="File status"
            onValueChange={setFileStatusFilter}
            options={fileStatusFilters}
            value={fileStatusFilter}
          />
        </div>
      </div>
      <ActionButton
        aria-label="Reset library filters"
        className={`${controlClasses.actionButtonCompact} inline-flex items-center gap-1.5`}
        disabled={!hasActiveFilters}
        onClick={resetFilters}
      >
        <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
        Reset
      </ActionButton>
    </section>
  );
}

export function LocalLibraryView() {
  return (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Library stats">
        {libraryStats.map((stat) => (
          <LibraryStatCard key={stat.label} stat={stat} />
        ))}
      </div>

      <section className="flex min-h-0 flex-1 flex-col gap-4">
        <LibraryFilterBar />

        <div className="min-h-0 flex-1 overflow-y-auto pb-1 pr-1" aria-label="Local library tracks" role="region">
          <EmptyStateCard
            body="Track rows will appear here as the library endpoints are wired in."
            className="text-left"
            title="Local library track list"
          />
        </div>
      </section>
    </section>
  );
}
