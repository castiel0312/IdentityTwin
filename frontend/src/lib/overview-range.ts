export type OverviewRange = "24h" | "7d" | "30d";

const HOURS: Record<OverviewRange, number> = { "24h": 24, "7d": 24 * 7, "30d": 24 * 30 };

export function createOverviewRange(range: OverviewRange, end = new Date()) {
  const start = new Date(end.getTime() - HOURS[range] * 3_600_000);
  return { start: start.toISOString(), end: end.toISOString() };
}
