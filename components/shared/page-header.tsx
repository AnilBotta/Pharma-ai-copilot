"use client";

import type { LucideIcon } from "lucide-react";

import { Enter } from "@/components/motion/primitives";
import { cn } from "@/lib/utils";

/**
 * The page's one and only <h1>.
 *
 * The topbar used to render a second <h1> from a hardcoded route map that
 * covered six of fifteen routes — so most pages announced themselves twice,
 * once correctly and once as "Pharma R&D Copilot". That map is gone and the
 * topbar carries a breadcrumb instead, leaving this as the single heading.
 *
 * The `"use client"` above is load-bearing and was missing: this imports
 * Framer Motion, and it only worked because all fourteen consumers happen to
 * be client components themselves. The first server page to render it would
 * have thrown.
 */
export function PageHeader({
  title,
  description,
  icon: Icon,
  iconClassName,
  actions,
  className,
}: {
  title: string;
  description?: string;
  icon?: LucideIcon;
  iconClassName?: string;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <Enter
      className={cn(
        "flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between",
        className
      )}
    >
      <div className="flex items-start gap-3.5">
        {Icon && (
          <div
            className={cn(
              // Was three hardcoded palette colours; follows the brand tokens
              // now, so it shifts with the theme like everything else.
              "mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-xl border border-primary/15 bg-primary/8 text-primary",
              iconClassName
            )}
          >
            <Icon className="size-5" />
          </div>
        )}
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
            {title}
          </h1>
          {description && (
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
              {description}
            </p>
          )}
        </div>
      </div>
      {actions && (
        <div className="flex shrink-0 items-center gap-2">{actions}</div>
      )}
    </Enter>
  );
}
