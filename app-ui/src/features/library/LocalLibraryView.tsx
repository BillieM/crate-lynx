import { Clock3, Link2, Music2, Unlink } from "lucide-react";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { surfaceClasses, textClasses } from "../../styles/componentClasses";

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

export function LocalLibraryView() {
  return (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Library stats">
        {libraryStats.map((stat) => (
          <LibraryStatCard key={stat.label} stat={stat} />
        ))}
      </div>

      <section className="flex min-h-0 flex-1 flex-col gap-4">
        <div className={surfaceClasses.dashedPlaceholder} aria-label="Library filters shell">
          <h2 className={textClasses.label}>Library filters</h2>
        </div>

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
