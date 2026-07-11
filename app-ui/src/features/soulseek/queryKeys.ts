import type { QueryKey } from "@tanstack/react-query";

export const soulseekQueryKeys = {
  all: ["soulseek"] as const,
  acquisition: (acquisitionId: number | string | null) => ["soulseek", "acquisition", acquisitionId] as const,
  queue: () => ["soulseek", "queue"] as const,
  status: () => ["soulseek", "status"] as const,
};

export function soulseekQueueInvalidationKeys(): QueryKey[] {
  return [soulseekQueryKeys.all];
}
