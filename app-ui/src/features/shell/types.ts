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

export type ViewConfig = {
  actionLabels: string[];
  icon: "spark" | "playlist" | "library" | "settings" | "tool";
  id: string;
  playlistResourceId?: number;
  title: string;
};

export type PlaylistSyncViewState = {
  playlistId: number;
  status: OperationStatus;
};
