"use client";

import type { LucideIcon } from "lucide-react";
import { TrendingDown, TrendingUp } from "lucide-react";

import { Enter } from "@/components/motion/primitives";
import { cn } from "@/lib/utils";

export interface StatCardProps {
  label: string;
  value: string;
  delta?: string;
  deltaPositive?: boolean;
  icon: LucideIcon;
  iconClassName?: string;
  hint?: string;
  delay?: number;
}

export function StatCard({
  label,
  value,
  delta,
  deltaPositive = true,
  icon: Icon,
  iconClassName,
  hint,
  delay = 0,
}: StatCardProps) {
  return (
    <Enter
      delay={delay}
      className="glass group relative overflow-hidden rounded-xl p-5 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-e3"
    >
      <div className="pointer-events-none absolute -top-12 -right-12 size-32 rounded-full bg-primary/10 blur-2xl transition-all duration-500 group-hover:bg-primary/20" />
      <div className="relative flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-2xs font-medium text-muted-foreground">
            {label}
          </p>
          <p className="metric mt-1.5 text-2xl">{value}</p>
          <div className="mt-2 flex items-center gap-2">
            {delta && (
              // A delta is a reading, so it takes status colour. Up is not
              // automatically good — the caller says which it is.
              <span
                className={cn(
                  "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-2xs font-medium",
                  deltaPositive
                    ? "bg-success-surface text-success"
                    : "bg-danger-surface text-danger"
                )}
              >
                {deltaPositive ? (
                  <TrendingUp className="size-3" />
                ) : (
                  <TrendingDown className="size-3" />
                )}
                {delta}
              </span>
            )}
            {hint && (
              <span className="truncate text-2xs text-muted-foreground">
                {hint}
              </span>
            )}
          </div>
        </div>
        <div
          className={cn(
            "flex size-10 shrink-0 items-center justify-center rounded-xl border border-primary/15 bg-primary/8",
            iconClassName
          )}
        >
          <Icon className="size-5 text-primary" />
        </div>
      </div>
    </Enter>
  );
}
