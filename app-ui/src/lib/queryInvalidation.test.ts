import { QueryClient } from "@tanstack/react-query";

import { invalidateQueryKeys, compactQueryKeys } from "./queryInvalidation";

describe("query invalidation", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("compacts duplicate query keys and keys covered by broader prefixes", () => {
    expect(
      compactQueryKeys([
        ["library", "tracks"],
        ["library"],
        ["library", "tracks"],
        ["playlists"],
        ["playlists", "list"],
        ["soulseek"],
        ["soulseek", "queue"],
      ]),
    ).toEqual([
      ["library"],
      ["playlists"],
      ["soulseek"],
    ]);
  });

  it("compares object query key parts structurally", () => {
    expect(
      compactQueryKeys([
        ["playlists", "proposals", "list", { confidenceBand: "high" }],
        ["playlists", "proposals", "list", { confidenceBand: "high" }],
        ["playlists", "proposals", "list", { confidenceBand: "low" }],
      ]),
    ).toEqual([
      ["playlists", "proposals", "list", { confidenceBand: "high" }],
      ["playlists", "proposals", "list", { confidenceBand: "low" }],
    ]);
  });

  it("invalidates only compacted query keys", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    await invalidateQueryKeys(queryClient, [
      ["library", "tracks"],
      ["library"],
      ["library", "tracks"],
      ["playlists"],
      ["playlists", "list"],
    ]);

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["library"] });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["playlists"] });
    expect(invalidateSpy).toHaveBeenCalledTimes(2);
  });
});
