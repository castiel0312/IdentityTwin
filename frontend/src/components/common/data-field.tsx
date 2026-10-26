import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function DataField({
  label,
  children,
  className,
  mono,
}: {
  label: string;
  children: ReactNode;
  className?: string;
  mono?: boolean;
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <dt className="text-2xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">{label}</dt>
      <dd className={cn("break-words text-sm leading-relaxed text-foreground", mono && "font-mono text-xs text-muted-foreground")}>
        {children ?? "—"}
      </dd>
    </div>
  );
}
