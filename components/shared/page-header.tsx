import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

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
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
      className={cn("flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between", className)}
    >
      <div className="flex items-start gap-3.5">
        {Icon && (
          <div
            className={cn(
              "mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-xl border border-blue-500/15 bg-gradient-to-br from-blue-600/10 to-violet-600/10 text-blue-600 dark:text-blue-400",
              iconClassName
            )}
          >
            <Icon className="size-5" />
          </div>
        )}
        <div>
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{title}</h1>
          {description && (
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{description}</p>
          )}
        </div>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </motion.div>
  );
}
