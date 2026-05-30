import { describe, expect, it } from "vitest";

import {
  buildMaintenanceNavItems,
  buildToolNavItems,
  getViewIdFromPath,
  localDedupeViewId,
  soulseekQueueViewId,
} from "./viewRegistry";

describe("viewRegistry", () => {
  it("registers the local dedupe tool route and nav item", () => {
    expect(getViewIdFromPath("/tools/dedupe")).toBe(localDedupeViewId);
    expect(buildToolNavItems(4)[0]).toEqual({
      badge: 4,
      id: localDedupeViewId,
      label: "Deduplicate tracks",
      tone: "pending",
    });
  });

  it("redirects the removed missing route to Soulseek and omits missing nav", () => {
    expect(getViewIdFromPath("/missing")).toBe(soulseekQueueViewId);
    expect(
      buildMaintenanceNavItems({
        proposalCount: 3,
        relationshipCount: 4,
        soulseekCount: 5,
        unidentifiedCount: 6,
      }).map((item) => item.label),
    ).toEqual(["Link proposals", "Soulseek queue", "Streaming relationships", "Unidentified"]);
  });
});
