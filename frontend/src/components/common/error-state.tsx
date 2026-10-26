import { AlertTriangle, LockKeyhole, RefreshCw, SearchX, WifiOff } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

export function ErrorState({
  error,
  onRetry,
  title,
  className,
  extra,
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
  className?: string;
  extra?: ReactNode;
}) {
  const apiError = error instanceof ApiError ? error : null;
  const isPermission = apiError?.status === 401 || apiError?.status === 403;
  const isNotFound = apiError?.status === 404;
  const isNetwork = error instanceof TypeError;
  const Icon = isPermission ? LockKeyhole : isNotFound ? SearchX : isNetwork ? WifiOff : AlertTriangle;
  const resolvedTitle =
    title ??
    (isPermission
      ? "Access denied"
      : isNotFound
        ? "Record not found"
        : isNetwork
          ? "Backend unreachable"
          : "Could not load this view");
  const message =
    apiError?.message ??
    (error instanceof Error
      ? error.message
      : isNetwork
        ? "The console could not reach the API. Check that the backend is running."
        : "An unexpected error occurred.");

  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-start gap-3 rounded-2xl border border-signal-isolated/25 bg-signal-isolated/[0.045] p-6",
        className,
      )}
    >
      <div className="flex items-center gap-2.5 text-signal-isolated">
        <span className="flex h-7 w-7 items-center justify-center rounded-full border border-signal-isolated/30 bg-signal-isolated/10">
          <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
        <h3 className="text-sm font-medium text-foreground">{resolvedTitle}</h3>
      </div>
      <p className="text-sm leading-relaxed text-muted-foreground">{message}</p>
      {apiError?.code ? (
        <p className="font-mono text-xs text-muted-foreground/80">Server code: {apiError.code}</p>
      ) : null}
      {extra}
      {onRetry && !isPermission && !isNotFound ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
          Retry request
        </Button>
      ) : null}
    </div>
  );
}
