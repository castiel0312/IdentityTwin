import { cva, type VariantProps } from "class-variance-authority";
import type * as React from "react";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-1 text-2xs font-semibold uppercase tracking-[0.12em] transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background",
  {
    variants: {
      variant: {
        default: "border-primary/30 bg-primary/10 text-primary",
        secondary: "border-border bg-secondary text-secondary-foreground",
        outline: "border-border/80 bg-transparent text-muted-foreground",
        success: "border-signal-normal/25 bg-signal-normal/10 text-signal-normal",
        warning: "border-signal-restricted/30 bg-signal-restricted/10 text-signal-restricted",
        danger: "border-signal-isolated/30 bg-signal-isolated/10 text-signal-isolated",
        info: "border-mint-muted/30 bg-mint/10 text-mint",
        muted: "border-border/70 bg-muted/60 text-muted-foreground",
        violet: "border-signal-decoy/30 bg-signal-decoy/10 text-signal-decoy",
        mint: "border-transparent bg-mint text-background",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
