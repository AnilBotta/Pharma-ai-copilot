import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * `tone` replaces the hand-rolled `border-destructive/40 bg-destructive/5`
 * pattern, which appeared on fourteen cards across the app with three
 * different opacity pairs between them. `variant="dashed"` replaces the
 * `border-dashed` that marks every advisory (agent) surface.
 *
 * Both are additive: `<Card className="…">` keeps working identically, so the
 * routes that have not been touched yet are unaffected.
 */
const cardVariants = cva(
  "flex flex-col gap-6 rounded-xl border py-6 text-card-foreground",
  {
    variants: {
      variant: {
        default: "bg-card shadow-e1",
        flush: "bg-card shadow-none",
        elevated: "bg-card shadow-e3",
        // Advisory surfaces. The agent's opinion is deliberately drawn as a
        // weaker thing than the engine's record.
        dashed: "border-dashed bg-card shadow-none",
        interactive:
          "bg-card shadow-e1 transition-colors hover:border-primary/40 focus-within:border-primary/40",
      },
      tone: {
        neutral: "",
        success: "border-success-border bg-success-surface",
        warning: "border-warning-border bg-warning-surface",
        info: "border-info-border bg-info-surface",
        danger: "border-danger-border bg-danger-surface",
      },
    },
    defaultVariants: { variant: "default", tone: "neutral" },
  }
);

export type CardTone = NonNullable<VariantProps<typeof cardVariants>["tone"]>;

function Card({
  className,
  variant,
  tone,
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof cardVariants>) {
  return (
    <div
      data-slot="card"
      className={cn(cardVariants({ variant, tone }), className)}
      {...props}
    />
  );
}

function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-header"
      className={cn(
        "@container/card-header grid auto-rows-min grid-rows-[auto_auto] items-start gap-1.5 px-6 has-data-[slot=card-action]:grid-cols-[1fr_auto] [.border-b]:pb-6",
        className
      )}
      {...props}
    />
  );
}

function CardTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-title"
      className={cn("leading-none font-semibold", className)}
      {...props}
    />
  );
}

function CardDescription({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-description"
      className={cn("text-muted-foreground text-sm", className)}
      {...props}
    />
  );
}

function CardAction({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-action"
      className={cn(
        "col-start-2 row-span-2 row-start-1 self-start justify-self-end",
        className
      )}
      {...props}
    />
  );
}

function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-content"
      className={cn("px-6", className)}
      {...props}
    />
  );
}

function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-footer"
      className={cn("flex items-center px-6 [.border-t]:pt-6", className)}
      {...props}
    />
  );
}

export {
  Card,
  cardVariants,
  CardHeader,
  CardFooter,
  CardTitle,
  CardAction,
  CardDescription,
  CardContent,
};