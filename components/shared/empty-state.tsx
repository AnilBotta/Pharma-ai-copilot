"use client";

import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function EmptyState({
  icon: Icon,
  title,
  description,
  actionLabel,
  onAction,
  className,
  compact = false,
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  className?: string;
  compact?: boolean;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      className={cn(
        "flex flex-col items-center justify-center text-center",
        compact ? "gap-2 py-8" : "gap-3 rounded-xl border border-dashed py-16",
        className
      )}
    >
      <div className="relative">
        <div className="absolute inset-0 animate-pulse-ring rounded-2xl bg-blue-500/20" />
        <div className="relative flex size-12 items-center justify-center rounded-2xl border border-blue-500/20 bg-gradient-to-br from-blue-600/10 to-violet-600/10 text-blue-600 dark:text-blue-400">
          <Icon className="size-6" />
        </div>
      </div>
      <div className="mt-2">
        <p className={cn("font-medium", compact ? "text-sm" : "text-base")}>{title}</p>
        {description && (
          <p className={cn("mx-auto mt-1 max-w-sm text-sm text-muted-foreground", compact && "max-w-xs")}>
            {description}
          </p>
        )}
      </div>
      {actionLabel && onAction && (
        <Button size="sm" className="mt-2" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </motion.div>
  );
}
