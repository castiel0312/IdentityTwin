import { Info, ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function InfoNote({
  children,
  tone = "info",
  className,
  title,
}: {
  children: ReactNode;
  tone?: "info" | "warning" | "danger" | "success";
  className?: string;
  title?: string;
}) {
  const tones = {
    info: "border-mint-muted/20 bg-mint/[0.045] text-foreground",
    warning: "border-signal-restricted/25 bg-signal-restricted/[0.045] text-foreground",
    danger: "border-signal-isolated/25 bg-signal-isolated/[0.045] text-foreground",
    success: "border-signal-normal/25 bg-signal-normal/[0.045] text-foreground",
  } as const;
  const iconTones = {
    info: "text-mint",
    warning: "text-signal-restricted",
    danger: "text-signal-isolated",
    success: "text-signal-normal",
  } as const;
  const Icon = tone === "danger" || tone === "warning" ? ShieldAlert : Info;
  return (
    <div className={cn("flex gap-3 rounded-xl border p-4 text-sm", tones[tone], className)}>
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", iconTones[tone])} aria-hidden="true" />
      <div className="space-y-1">
        {title ? <p className="text-sm font-medium text-foreground">{title}</p> : null}
        <div className="text-[0.8125rem] leading-relaxed text-muted-foreground">{children}</div>
      </div>
    </div>
  );
}
