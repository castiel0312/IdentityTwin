import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export function TableLoading({ rows = 6, columns = 5, className }: { rows?: number; columns?: number; className?: string }) {
  return (
    <div className={cn("space-y-3.5 p-5", className)} aria-busy="true" aria-label="Loading data">
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div key={rowIndex} className="grid gap-3" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
          {Array.from({ length: columns }).map((__, columnIndex) => (
            <Skeleton key={columnIndex} className={cn("h-6", columnIndex === 0 ? "w-4/5" : "w-3/5")} />
          ))}
        </div>
      ))}
    </div>
  );
}

export function CardsLoading({ count = 4, className }: { count?: number; className?: string }) {
  return (
    <div className={cn("grid gap-4 sm:grid-cols-2 xl:grid-cols-4", className)} aria-busy="true" aria-label="Loading metrics">
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="rounded-2xl border border-border/80 bg-card p-5">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="mt-5 h-8 w-20" />
          <Skeleton className="mt-3 h-3 w-32" />
        </div>
      ))}
    </div>
  );
}

export function DetailLoading({ className }: { className?: string }) {
  return (
    <div className={cn("space-y-4", className)} aria-busy="true" aria-label="Loading detail">
      <Skeleton className="h-9 w-1/3" />
      <Skeleton className="h-4 w-2/3" />
      <div className="grid gap-4 lg:grid-cols-3">
        <Skeleton className="h-48 lg:col-span-2" />
        <Skeleton className="h-48" />
      </div>
    </div>
  );
}
