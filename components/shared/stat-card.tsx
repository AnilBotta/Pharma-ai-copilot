"use client";

import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import { TrendingDown, TrendingUp } from "lucide-react";

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
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay, ease: [0.22, 1, 0.36, 1] }}
      className="glass group relative overflow-hidden rounded-xl p-5 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-lg hover:shadow-blue-900/10"
    >
      <div className="pointer-events-none absolute -top-12 -right-12 size-32 rounded-full bg-gradient-to-br from-blue-500/10 to-violet-500/10 blur-2xl transition-all duration-500 group-hover:from-blue-500/20 group-hover:to-violet-500/20" />
      <div className="relative flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-[13px] font-medium text-muted-foreground">{label}</p>
          <p className="mt-1.5 text-2xl font-semibold tracking-tight">{value}</p>
          <div className="mt-2 flex items-center gap-2">
            {delta && (
              <span
                className={cn(
                  "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[11px] font-medium",
                  deltaPositive
                    ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                    : "bg-rose-500/10 text-rose-600 dark:text-rose-400"
                )}
              >
                {deltaPositive ? <TrendingUp className="size-3" /> : <TrendingDown className="size-3" />}
                {delta}
              </span>
            )}
            {hint && <span className="truncate text-[11px] text-muted-foreground">{hint}</span>}
          </div>
        </div>
        <div
          className={cn(
            "flex size-10 shrink-0 items-center justify-center rounded-xl border border-blue-500/15 bg-gradient-to-br from-blue-600/10 to-violet-600/10",
            iconClassName
          )}
        >
          <Icon className="size-5 text-blue-600 dark:text-blue-400" />
        </div>
      </div>
    </motion.div>
  );
}
