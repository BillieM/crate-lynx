import { EmptyStateCard } from "../../components/EmptyStateCard";
import { layoutClasses } from "../../styles/componentClasses";
import { routeFallbackCopyFor, type RouteFallbackKind } from "./routeFallback";

export function RouteFallbackView({ kind }: { kind: RouteFallbackKind }) {
  const copy = routeFallbackCopyFor(kind);

  return (
    <EmptyStateCard
      body={copy.body}
      className={layoutClasses.emptyStateNarrow}
      role={kind === "loading" ? "status" : "alert"}
      title={copy.title}
      tone={kind === "loading" ? "neutral" : "error"}
    />
  );
}
