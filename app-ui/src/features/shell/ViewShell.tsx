import { Component, Suspense, useState, type ReactNode } from "react";
import { ActionButton } from "../../components/ActionButton";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { controlClasses, layoutClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import type { PlaylistSyncViewState } from "./types";
import type { AppViewEntry } from "./viewRegistry";

class ViewErrorBoundary extends Component<
  { children: ReactNode; onRetry: () => void; viewTitle: string },
  { error: Error | null }
> {
  state = { error: null } as { error: Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch() {
    // The recovery UI is intentionally local to the failed route. Other views
    // remain usable while a replaced or temporarily unavailable chunk retries.
  }

  render() {
    if (this.state.error) {
      return (
        <div className={`${surfaceClasses.emptyState} ${layoutClasses.emptyStateNarrow} border-ctp-red/40 text-left`} role="alert">
          <h2 className={textClasses.title}>{this.props.viewTitle} could not load</h2>
          <p className={`mt-1.5 ${textClasses.bodyMutedRelaxed}`}>
            This view's code could not be loaded. Check the connection and retry without leaving your current route.
          </p>
          <ActionButton className={`mt-3 ${controlClasses.actionButtonCompact}`} onClick={this.props.onRetry}>
            Retry view
          </ActionButton>
        </div>
      );
    }

    return this.props.children;
  }
}

export function ViewShell({
  activeViewId,
  playlistSyncState,
  view,
}: {
  activeViewId: string;
  playlistSyncState?: PlaylistSyncViewState;
  view: AppViewEntry;
}) {
  const isActive = activeViewId === view.id;
  const [retryKey, setRetryKey] = useState(0);

  return (
    <div
      aria-hidden={!isActive}
      className={isActive ? "flex min-h-0 flex-1 flex-col overflow-hidden" : "hidden"}
      data-view-active={isActive ? "true" : "false"}
      id={view.id}
    >
      {isActive ? (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-4 sm:p-6">
          <ViewErrorBoundary
            key={retryKey}
            onRetry={() => setRetryKey((current) => current + 1)}
            viewTitle={view.title}
          >
            <Suspense
              fallback={
                <EmptyStateCard
                  body="Loading view..."
                  className={layoutClasses.emptyStateNarrow}
                  role="status"
                  title="Loading"
                />
              }
            >
              {view.render({ isActive, playlistSyncState, retryKey })}
            </Suspense>
          </ViewErrorBoundary>
        </div>
      ) : null}
    </div>
  );
}
