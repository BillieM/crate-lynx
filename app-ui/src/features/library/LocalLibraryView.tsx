import { EmptyStateCard } from "../../components/EmptyStateCard";
import { surfaceClasses, textClasses } from "../../styles/componentClasses";

function LibraryShellPanel({ title }: { title: string }) {
  return (
    <section className={`${surfaceClasses.dashedPlaceholder} min-h-24`}>
      <h2 className={textClasses.label}>{title}</h2>
    </section>
  );
}

export function LocalLibraryView() {
  return (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Library stats shell">
        <LibraryShellPanel title="Total tracks" />
        <LibraryShellPanel title="Linked tracks" />
        <LibraryShellPanel title="Pending tracks" />
        <LibraryShellPanel title="Unlinked tracks" />
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
