import { cva, type VariantProps } from "class-variance-authority";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full text-sm font-medium transition-[background-color,border-color,color,box-shadow,transform] duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-45 active:translate-y-px",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow-[0_14px_34px_-18px_hsl(var(--primary)/0.9)] hover:bg-primary-hover",
        secondary: "border border-border bg-elevated text-foreground hover:border-muted-foreground/40 hover:bg-secondary",
        outline: "border border-border bg-transparent text-foreground hover:border-primary/40 hover:bg-primary/[0.06] hover:text-foreground",
        ghost: "text-secondary-foreground hover:bg-white/[0.05] hover:text-foreground",
        destructive: "bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90",
        link: "rounded-none text-primary underline-offset-4 hover:text-primary-hover hover:underline",
        mint: "bg-mint text-background hover:bg-mint-muted",
      },
      size: {
        default: "h-10 px-5 py-2",
        sm: "h-8 gap-1.5 px-3.5 text-xs",
        lg: "h-12 px-7 text-[0.9375rem]",
        icon: "h-9 w-9",
        "icon-sm": "h-8 w-8",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export type ButtonVariants = VariantProps<typeof buttonVariants>;