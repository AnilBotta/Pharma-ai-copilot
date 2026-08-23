"use client";

import * as React from "react";
import * as ProgressPrimitive from "@radix-ui/react-progress";

import { cn } from "@/lib/utils";

/**
 * Tone is the tokenised way to colour the fill.
 *
 * `indicatorClassName` is KEPT and still wins when both are passed. Three
 * call sites pass `is_ready ? "bg-emerald-500" : "bg-amber-500"` through it,
 * and that ternary is the no-false-green rule made visible — a gate at 93%
 * with one unsatisfied mandatory requirement shows an amber bar, deliberately
 * contradicting a reading of "nearly done". Removing the prop would have
 * broken that rule in three places at once, so it stays until each call site
 * has moved to `tone` on purpose.
 */
const TONE_FILL = {
  brand: "bg-primary",
  success: "bg-success-solid",
  warning: "bg-warning-solid",
  danger: "bg-danger-solid",
  neutral: "bg-muted-foreground/40",
} as const;

export type ProgressTone = keyof typeof TONE_FILL;

function Progress({
  className,
  value,
  tone = "brand",
  indicatorClassName,
  valueText,
  ...props
}: React.ComponentProps<typeof ProgressPrimitive.Root> & {
  tone?: ProgressTone;
  indicatorClassName?: string;
  /**
   * What a screen reader should say instead of the bare number. A gate reads
   * "93.4 percent, not ready" rather than "93" — the percentage alone is the
   * misreading this component exists to prevent, and that applies to people
   * listening to it too.
   */
  valueText?: string;
}) {
  return (
    <ProgressPrimitive.Root
      data-slot="progress"
      aria-valuetext={valueText}
      className={cn(
        "relative h-2 w-full overflow-hidden rounded-full bg-muted",
        className
      )}
      {...props}
    >
      <ProgressPrimitive.Indicator
        data-slot="progress-indicator"
        data-tone={tone}
        className={cn(
          "h-full w-full flex-1 transition-all",
          TONE_FILL[tone],
          indicatorClassName
        )}
        style={{ transform: `translateX(-${100 - (value || 0)}%)` }}
      />
    </ProgressPrimitive.Root>
  );
}

export { Progress };
