import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  description,
  eyebrow,
  actions,
  className,
}: {
  title: string;
  description?: ReactNode;
  eyebrow?: string;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between", className)}>
      <div className="min-w-0 space-y-3">
        {eyebrow ? (
          <p className="editorial-eyebrow">
            <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden="true" />
            {eyebrow}
          </p>
        ) : null}
        <h1 className="editorial-title text-[2rem] sm:text-[2.6rem]">{title}</h1>
        {description ? (
          <div className="max-w-3xl text-sm leading-6 text-muted-foreground sm:text-[0.9375rem]">{description}</div>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}
