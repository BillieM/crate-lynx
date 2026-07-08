export type RouteFallbackKind = "generated-run" | "loading" | "playlist" | "unknown";

const routeFallbackCopy = {
  "generated-run": {
    body: "This generated run may have been deleted or expired.",
    title: "Generated run unavailable",
  },
  loading: {
    body: "Loading navigation state...",
    title: "Loading",
  },
  playlist: {
    body: "This playlist is no longer available or is not selected for full sync.",
    title: "Playlist unavailable",
  },
  unknown: {
    body: "This route is not available.",
    title: "Page not found",
  },
} satisfies Record<RouteFallbackKind, { body: string; title: string }>;

export function routeFallbackCopyFor(kind: RouteFallbackKind) {
  return routeFallbackCopy[kind];
}

export function routeFallbackTitle(kind: RouteFallbackKind) {
  return routeFallbackCopy[kind].title;
}

export function routeFallbackKindFromPath(pathname: string): RouteFallbackKind {
  if (/^\/generated-runs\/[^/]+\/?$/.test(pathname)) {
    return "generated-run";
  }

  if (/^\/playlists\/[^/]+\/?$/.test(pathname)) {
    return "playlist";
  }

  return "unknown";
}
