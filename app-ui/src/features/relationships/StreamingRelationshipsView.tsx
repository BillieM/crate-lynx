import { EmptyStateCard } from "../../components/EmptyStateCard";
import { layoutClasses, textClasses } from "../../styles/componentClasses";

export function StreamingRelationshipsView() {
  return (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      <div>
        <h2 className={textClasses.sectionTitle}>Relationship queue</h2>
        <p className={`mt-1 ${textClasses.bodyMuted}`}>Streaming-to-streaming suggestions sorted by confidence.</p>
      </div>

      <div className="flex min-h-0 flex-1 items-center justify-center">
        <EmptyStateCard
          body="Pending streaming-to-streaming relationship suggestions will appear here for review."
          className={`${layoutClasses.emptyStateNarrow} text-left`}
          title="Streaming relationships"
        />
      </div>
    </section>
  );
}
