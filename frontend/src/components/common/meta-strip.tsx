import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type MetaStripItem = {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
};

/**
 * Dense, editorial context strip. Every value must come from server state or
 * be a plainly derived presentation of it (page counts, filter state).
 */
export function MetaStrip({ items, className }: { items: MetaStripItem[]; className?: string }) {
  return (
    <dl
      className={cn(
        "grid gap-px overflow-hidden rounded-2xl border border-border/80 bg-border/50 sm:grid-cols-2 xl:grid-cols-4",
        className,
      )}
    >
      {items.map((item) => (
        <div key={item.label} className="bg-card/95 px-5 py-4">
          <dt className="text-2xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">{item.label}</dt>
          <dd className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm font-medium text-foreground">
            {item.value}
          </dd>
          {item.hint ? <p className="mt-1 text-[11px] leading-4 text-muted-foreground">{item.hint}</p> : null}
        </div>
      ))}
    </dl>
  );
}
