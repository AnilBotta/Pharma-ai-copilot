"use client";

import { motion } from "framer-motion";
import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

export function AgentRunLoader({
  steps,
  activeStep,
  agentName,
  agentIcon: Icon,
  agentColor = "text-blue-600 dark:text-blue-400",
  compact = false,
}: {
  steps: string[];
  activeStep: number;
  agentName: string;
  agentIcon: React.ComponentType<{ className?: string }>;
  agentColor?: string;
  compact?: boolean;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      className="glass mx-auto w-full max-w-md rounded-2xl p-6"
    >
      <div className="flex items-center gap-3">
        <div className="relative">
          <div className={cn("absolute inset-0 animate-pulse-ring rounded-xl bg-blue-500/30", agentColor === "text-emerald-600 dark:text-emerald-400" ? "bg-emerald-500/30" : "")} />
          <div className={cn("relative flex size-10 items-center justify-center rounded-xl border bg-gradient-to-br from-blue-600/10 to-violet-600/10", agentColor)}>
            <Icon className="size-5" />
          </div>
        </div>
        <div>
          <p className="text-sm font-semibold">{agentName}</p>
          <p className="text-xs text-muted-foreground">Running analysis…</p>
        </div>
        <Loader2 className="ml-auto size-4 animate-spin text-primary" />
      </div>

      <div className="mt-5 space-y-2.5">
        {steps.map((step, i) => {
          const done = i < activeStep;
          const active = i === activeStep;
          return (
            <div key={step} className="flex items-center gap-2.5 text-[13px]">
              <div
                className={cn(
                  "flex size-4 shrink-0 items-center justify-center rounded-full border transition-colors",
                  done && "border-emerald-500/40 bg-emerald-500/15 text-emerald-500",
                  active && "border-blue-500/40 bg-blue-500/15 text-blue-500",
                  !done && !active && "border-border text-transparent"
                )}
              >
                {done ? (
                  <svg viewBox="0 0 10 10" className="size-2.5" fill="none">
                    <path d="M2 5l2 2 4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                  </svg>
                ) : active ? (
                  <span className="size-1.5 animate-pulse rounded-full bg-current" />
                ) : (
                  <span className="size-1.5 rounded-full bg-current opacity-30" />
                )}
              </div>
              <span
                className={cn(
                  "transition-colors",
                  active && "font-medium text-foreground",
                  done ? "text-muted-foreground" : "text-muted-foreground/70"
                )}
              >
                {step}
              </span>
              {active && (
                <span className="typing-dot ml-1 inline-flex gap-0.5">
                  <span className="size-1 rounded-full bg-current" />
                  <span className="size-1 rounded-full bg-current" />
                  <span className="size-1 rounded-full bg-current" />
                </span>
              )}
            </div>
          );
        })}
      </div>

      {!compact && (
        <div className="mt-5 h-1 overflow-hidden rounded-full bg-muted">
          <motion.div
            className="h-full rounded-full bg-gradient-to-r from-blue-600 to-violet-600"
            animate={{ width: `${Math.min(100, ((activeStep + 1) / steps.length) * 100)}%` }}
            transition={{ duration: 0.4 }}
          />
        </div>
      )}
    </motion.div>
  );
}
