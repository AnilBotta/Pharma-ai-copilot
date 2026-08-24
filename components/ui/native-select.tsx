import * as React from "react";
import { ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * A native `<select>` wearing the same tokens as `Input`.
 *
 * Four selects across the gate workspace each carried the same one-off
 * `h-9 w-full rounded-md border bg-transparent px-3 text-sm` — which gave them
 * no focus ring at all, and in dark mode left the option list to whatever the
 * OS decided, because `bg-transparent` inherits nothing an option can use.
 *
 * This stays a native select rather than adopting `components/ui/select.tsx`
 * (Radix) on purpose: one of these lives inside a Dialog and relies on
 * `<option disabled>` to say "Approve is not available yet". Swapping the
 * element would move focus management and that disabled semantics onto a new
 * implementation for no visual gain.
 */
function NativeSelect({
  className,
  children,
  ...props
}: React.ComponentProps<"select">) {
  return (
    <div className="relative">
      <select
        data-slot="native-select"
        className={cn(
          "border-input flex h-9 w-full appearance-none rounded-md border bg-transparent px-3 py-1 pr-9 text-sm shadow-xs outline-none transition-[color,box-shadow]",
          "dark:bg-input/30 [&>option]:bg-popover [&>option]:text-popover-foreground",
          "focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]",
          "disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground"
      />
    </div>
  );
}

export { NativeSelect };
