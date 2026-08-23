import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * Status colour lives in tokens, not in raw palette classes.
 *
 * The four semantic variants used to be `bg-emerald-500/12 text-emerald-700
 * dark:text-emerald-400` and friends — a second colour system running beside
 * the OKLCH tokens, tuned for light and merely inverted for dark. They now
 * read from `--success-*` / `--warning-*` / `--danger-*` / `--info-*`, which
 * are defined and separately tuned in both themes.
 *
 * Variant NAMES are unchanged, deliberately: 24 files pass them, and this is
 * a colour change rather than an API change.
 */
const badgeVariants = cva(
  "inline-flex items-center justify-center rounded-md border px-2 py-0.5 text-xs font-medium w-fit whitespace-nowrap shrink-0 [&>svg]:size-3 gap-1 [&>svg]:pointer-events-none transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        destructive: "border-transparent bg-danger-solid text-danger-on-solid",
        outline: "text-foreground",
        success: "border-success-border bg-success-surface text-success",
        warning: "border-warning-border bg-warning-surface text-warning",
        info: "border-info-border bg-info-surface text-info",
        muted: "border-transparent bg-neutral-surface text-muted-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

/**
 * The single source of truth for what a badge variant may be.
 *
 * Three files kept their own hand-written copy of this union — two of them
 * spelled differently — so adding a variant meant remembering to edit all
 * four. Derived from the cva definition instead, it cannot drift.
 */
export type BadgeVariant = NonNullable<
  VariantProps<typeof badgeVariants>["variant"]
>;

/**
 * `dot` and `asChild` are mutually exclusive in the type, not merely by
 * convention: Radix's Slot requires exactly one child, so adding the dot
 * alongside `asChild` would hand it a fragment of two and throw at runtime.
 * Expressing that as a union makes it a compile error instead.
 */
type BadgeProps = React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> &
  (
    | {
        asChild: true;
        dot?: never;
      }
    | {
        asChild?: false;
        /** Leading dot in the current text colour. Hand-rolled in three places. */
        dot?: boolean;
      }
  );

function Badge({
  className,
  variant,
  asChild = false,
  dot = false,
  children,
  ...props
}: BadgeProps) {
  const Comp = asChild ? Slot : "span";
  return (
    <Comp
      data-slot="badge"
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    >
      {dot ? (
        <>
          <span
            aria-hidden="true"
            className="size-1.5 shrink-0 rounded-full bg-current"
          />
          {children}
        </>
      ) : (
        children
      )}
    </Comp>
  );
}

export { Badge, badgeVariants };
