import { cn } from "@/lib/utils";

export function RiskMeter({ score, className }: { score: number; className?: string }) {
  const clamped = Math.min(100, Math.max(0, score));
  const tone =
    clamped >= 90
      ? "bg-signal-isolated"
      : clamped >= 60
        ? "bg-signal-decoy"
        : clamped >= 30
          ? "bg-signal-restricted"
          : "bg-signal-normal";
  const band = clamped >= 90 ? "Isolated" : clamped >= 60 ? "Elevated" : clamped >= 30 ? "Guarded" : "Normal";
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <div
        className="h-1.5 w-20 overflow-hidden rounded-full bg-white/[0.07]"
        role="meter"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Risk score ${clamped.toFixed(1)} of 100, ${band}`}
      >
        <div className={cn("h-full rounded-full transition-all duration-200", tone)} style={{ width: `${clamped}%` }} />
      </div>
      <span className="font-mono text-xs tabular-nums text-foreground">{clamped.toFixed(1)}</span>
      <span className="text-2xs uppercase tracking-[0.12em] text-muted-foreground">{band}</span>
    </div>
  );
}
