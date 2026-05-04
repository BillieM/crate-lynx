import type { OperationStatus } from "../../components/StatusMessage";
import type { ProgressStatus } from "./progress";

export type NavItem = {
  badge?: number;
  id: string;
  label: string;
  progress?: {
    complete: number;
    total: number;
  };
  tone: ProgressStatus | "alert" | "accent";
};

export type TopbarPillTone = "pill-info" | "pill-pending" | "pill-lib";

export type SearchResult = {
  id: number;
  kind: "playlist" | "streaming_track" | "local_track";
  route_path: string;
  subtitle: string;
  title: string;
};

export type SearchResponse = {
  query: string;
  results: SearchResult[];
};

export type ViewConfig = {
  actionLabels: string[];
  icon: "spark" | "playlist" | "library";
  id: string;
  playlistResourceId?: number;
  pillLabel: string;
  pillTone: TopbarPillTone;
  title: string;
};

export type PlaylistSyncViewState = {
  playlistId: number;
  status: OperationStatus;
};
