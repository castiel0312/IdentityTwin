import { Badge, type BadgeProps } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { titleCase } from "@/lib/format";

const trustStyles: Record<string, { variant: BadgeProps["variant"]; dot: string; label: string }> = {
  NORMAL: { variant: "success", dot: "bg-signal-normal", label: "Normal" },
  RESTRICTED: { variant: "warning", dot: "bg-signal-restricted", label: "Restricted" },
  DECOY: { variant: "violet", dot: "bg-signal-decoy", label: "Decoy" },
  ISOLATED: { variant: "danger", dot: "bg-signal-isolated", label: "Isolated" },
};

export function TrustBadge({ level, className }: { level: string | null | undefined; className?: string }) {
  const key = (level ?? "").toUpperCase();
  const style =
    trustStyles[key] ?? { variant: "muted" as const, dot: "bg-muted-foreground", label: level ?? "Unknown" };
  const srLabel = `Trust level: ${style.label}`;
  return (
    <Badge variant={style.variant} className={cn("gap-1.5", className)} aria-label={srLabel}>
      <span className={cn("h-1.5 w-1.5 rounded-full", style.dot)} aria-hidden="true" />
      {style.label}
    </Badge>
  );
}

const statusStyles: Record<string, BadgeProps["variant"]> = {
  completed: "success",
  reconciled_completed: "success",
  verified: "success",
  active: "success",
  approved: "success",
  accepted: "success",
  open: "info",
  under_review: "warning",
  processing: "warning",
  pending: "warning",
  require_step_up: "warning",
  restricted: "warning",
  decoy_completed: "violet",
  decoy_forward: "violet",
  rejected: "danger",
  blocked: "danger",
  revoked: "danger",
  provider_denied: "danger",
  failed: "danger",
  suspended: "danger",
  expired: "muted",
  resolved: "success",
  low: "muted",
  medium: "info",
  high: "warning",
  critical: "danger",
  allow: "success",
  sealed: "success",
  unsealed: "muted",
};

export function StatusBadge({ status, className }: { status: string | null | undefined; className?: string }) {
  const key = (status ?? "").toLowerCase();
  const label = titleCase(status ?? "unknown");
  return (
    <Badge variant={statusStyles[key] ?? "outline"} className={className} aria-label={`Status: ${label}`}>
      {label}
    </Badge>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  return <StatusBadge status={severity} />;
}
