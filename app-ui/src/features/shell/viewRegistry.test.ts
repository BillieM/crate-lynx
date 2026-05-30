import { describe, expect, it } from "vitest";

import {
  buildToolNavItems,
  getViewIdFromPath,
  localDedupeViewId,
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
});
