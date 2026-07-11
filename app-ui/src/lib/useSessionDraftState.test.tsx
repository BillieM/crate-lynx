import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { setSessionDraftCodec, useSessionDraftState } from "./useSessionDraftState";

describe("useSessionDraftState", () => {
  it("restores a meaningful draft after the originating view remounts", () => {
    const firstMount = renderHook(() => useSessionDraftState("draft:test", "initial"));

    act(() => firstMount.result.current[1]("edited"));
    firstMount.unmount();

    const secondMount = renderHook(() => useSessionDraftState("draft:test", "initial"));
    expect(secondMount.result.current[0]).toBe("edited");
    expect(secondMount.result.current[2]).toBe(true);
  });

  it("round-trips Set drafts through session storage", () => {
    const codec = setSessionDraftCodec<number>();
    const firstMount = renderHook(() => useSessionDraftState("draft:set", () => new Set<number>(), codec));

    act(() => firstMount.result.current[1](new Set([12, 27])));
    firstMount.unmount();

    const secondMount = renderHook(() => useSessionDraftState("draft:set", () => new Set<number>(), codec));
    expect(Array.from(secondMount.result.current[0])).toEqual([12, 27]);
  });
});
