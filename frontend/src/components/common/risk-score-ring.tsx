import { cn } from "@/lib/utils";

/**
 * Circular visualisation of a persisted risk score (0–100).
 * Renders exactly the score supplied by the API — it never derives or guesses a score.
 */
export function RiskScoreRing({
  score,
  size = 148,
  label = "Risk score",
  className,
}: {
  score: number | null | undefined;
  size?: number;
  label?: string;
  className?: string;
}) {
  const hasScore = typeof score === "number" && Number.isFinite(score);
  const clamped = hasScore ? Math.min(100, Math.max(0, score as number)) : 0;
  const band = !hasScore
    ? { label: "Unknown", color: "hsl(var(--muted-foreground))" }
    : clamped >= 90
      ? { label: "Isolated", color: "hsl(var(--signal-isolated))" }
      : clamped >= 60
        ? { label: "Elevated", color: "hsl(var(--signal-decoy))" }
        : clamped >= 30
          ? { label: "Guarded", color: "hsl(var(--signal-restricted))" }
          : { label: "Normal", color: "hsl(var(--signal-normal))" };
  const stroke = 6;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (clamped / 100) * circumference;

  return (
    <div className={cn("flex flex-col items-center gap-3", className)}>
      <div className="relative" style={{ width: size, height: size }}>
        <svg
          width={size}
          height={size}
          viewBox={`0 0 ${size} ${size}`}
          role="img"
          aria-label={hasScore ? `${label} ${clamped.toFixed(1)} of 100, ${band.label}` : `${label} unavailable`}
          className="-rotate-90"
        >
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="hsl(var(--border))"
            strokeWidth={stroke}
            opacity={0.55}
          />
          {hasScore ? (
            <circle
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              stroke={band.color}
              strokeWidth={stroke}
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={offset}
              style={{ transition: "stroke-dashoffset 220ms ease-out" }}
            />
          ) : null}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-0.5">
          <span className="font-mono text-2xl font-medium tabular-nums leading-none text-foreground">
            {hasScore ? clamped.toFixed(1) : "—"}
          </span>
          <span className="text-2xs uppercase tracking-[0.16em] text-muted-foreground">{band.label}</span>
        </div>
      </div>
      <p className="text-2xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">{label}</p>
    </div>
  );
}
