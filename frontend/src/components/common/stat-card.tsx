import type { LucideIcon } from "lucide-react";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import type { ReactNode } from "react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = "default",
  trend,
  className,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon?: LucideIcon;
  tone?: "default" | "danger" | "warning" | "success" | "violet";
  trend?: { value: string; direction: "up" | "down" };
  className?: string;
}) {
  const toneClasses = {
    default: "border-primary/25 bg-primary/10 text-primary",
    danger: "border-signal-isolated/25 bg-signal-isolated/10 text-signal-isolated",
    warning: "border-signal-restricted/25 bg-signal-restricted/10 text-signal-restricted",
    success: "border-signal-normal/25 bg-signal-normal/10 text-signal-normal",
    violet: "border-signal-decoy/25 bg-signal-decoy/10 text-signal-decoy",
  } as const;

  return (
    <Card className={cn("group relative overflow-hidden p-5 transition-colors duration-200 hover:border-border", className)}>
      <div
        className="pointer-events-none absolute -right-10 -top-12 h-28 w-28 rounded-full border border-white/[0.04]"
        aria-hidden="true"
      />
      <div className="flex items-start justify-between gap-3">
        <p className="text-2xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">{label}</p>
        {Icon ? (
          <span className={cn("flex h-8 w-8 items-center justify-center rounded-full border", toneClasses[tone])}>
            <Icon className="h-3.5 w-3.5" aria-hidden="true" />
          </span>
        ) : null}
      </div>
      <p className="metric-value mt-5">{value}</p>
      <div className="mt-2.5 flex items-center gap-2 text-xs text-muted-foreground">
        {trend ? (
          <span
            className={cn(
              "inline-flex items-center gap-0.5 font-medium",
              trend.direction === "up" ? "text-signal-normal" : "text-signal-restricted",
            )}
          >
            {trend.direction === "up" ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
            {trend.value}
          </span>
        ) : null}
        {hint ? <span className="leading-relaxed">{hint}</span> : null}
      </div>
    </Card>
  );
}
