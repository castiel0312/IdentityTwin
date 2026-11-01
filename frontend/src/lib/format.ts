const DATE_TIME_FORMATTER = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium",
  timeStyle: "short",
});

const RELATIVE_FORMATTER = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

const RELATIVE_DIVISIONS: ReadonlyArray<{
  amount: number;
  unit: Intl.RelativeTimeFormatUnit;
}> = [
  { amount: 60, unit: "second" },
  { amount: 60, unit: "minute" },
  { amount: 24, unit: "hour" },
  { amount: 7, unit: "day" },
  { amount: 4.34524, unit: "week" },
  { amount: 12, unit: "month" },
  { amount: Number.POSITIVE_INFINITY, unit: "year" },
];

function toDate(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function toFiniteNumber(value: number): number | null {
  return Number.isFinite(value) ? value : null;
}

function words(value: string | null | undefined): string[] {
  if (!value) return [];
  return value
    .replace(/[._-]+/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
}

export function formatDateTime(value: string | number | Date | null | undefined): string {
  const date = toDate(value);
  return date ? DATE_TIME_FORMATTER.format(date) : "—";
}

export function relativeTime(value: string | number | Date | null | undefined): string {
  const date = toDate(value);
  if (!date) return "—";
  let duration = (date.getTime() - Date.now()) / 1000;
  for (const division of RELATIVE_DIVISIONS) {
    if (Math.abs(duration) < division.amount) {
      return RELATIVE_FORMATTER.format(Math.round(duration), division.unit);
    }
    duration /= division.amount;
  }
  return RELATIVE_FORMATTER.format(Math.round(duration), "year");
}

export function formatMoney(amount: number, currency = "USD"): string {
  const value = toFiniteNumber(amount);
  if (value === null) return "—";
  const code = (currency || "USD").toUpperCase();
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: code,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${code} ${value.toFixed(2)}`;
  }
}

export function formatNumber(value: number): string {
  const number = toFiniteNumber(value);
  if (number === null) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(number);
}

export function formatPercent(value: number): string {
  const number = toFiniteNumber(value);
  if (number === null) return "—";
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(number)}%`;
}

export function humanizeCode(value: string | null | undefined): string {
  const parts = words(value);
  if (!parts.length) return "—";
  const joined = parts.join(" ").toLowerCase();
  return joined.charAt(0).toUpperCase() + joined.slice(1);
}

export function titleCase(value: string | null | undefined): string {
  const parts = words(value);
  if (!parts.length) return "—";
  return parts
    .map((part) => {
      const lower = part.toLowerCase();
      return lower.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join(" ");
}

export function truncateMiddle(value: string, max = 24): string {
  if (value.length <= max) return value;
  const keep = Math.max(1, Math.floor((max - 1) / 2));
  return `${value.slice(0, keep)}…${value.slice(value.length - keep)}`;
}

export function newIdempotencyKey(prefix: string): string {
  const cryptoApi = globalThis.crypto as (Crypto & { randomUUID?: () => string }) | undefined;
  const random =
    cryptoApi?.randomUUID?.() ??
    `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
  return `${prefix}-${random}`;
}
