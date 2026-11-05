import { describe, expect, it } from "vitest";
import { createOverviewRange } from "@/lib/overview-range";

describe("createOverviewRange", () => {
  it("uses the current fetch time as the end of each analytics window", () => {
    const first = createOverviewRange("24h", new Date("2026-11-04T10:00:00.000Z"));
    const refreshed = createOverviewRange("24h", new Date("2026-11-04T10:05:00.000Z"));

    expect(first).toEqual({
      start: "2026-11-03T10:00:00.000Z",
      end: "2026-11-04T10:00:00.000Z",
    });
    expect(refreshed).toEqual({
      start: "2026-11-03T10:05:00.000Z",
      end: "2026-11-04T10:05:00.000Z",
    });
  });
});
