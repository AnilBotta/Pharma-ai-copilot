"use client";

import { useTheme } from "next-themes";
import { Toaster as Sonner, type ToasterProps } from "sonner";

/**
 * Transient confirmation for actions that otherwise report nothing.
 *
 * The app had no toast system at all. Failures surfaced as an inline card at
 * the TOP of the page — so acting on the fourteenth requirement, three
 * thousand pixels down the gate workspace, produced an error message the
 * person would never see. Successes reported nothing whatsoever until a full
 * reload landed.
 *
 * The division of labour is deliberate, and is worth keeping to:
 *
 *   page-level load failure   -> inline card. Blocking, persistent, and there
 *                                is nothing else to look at.
 *   action outcome           -> toast. Attached to a thing the person just
 *                                did, and safe to miss on a second reading.
 *   audit-consequential act  -> toast AND the in-place record. A gate
 *                                decision must not be acknowledged only by
 *                                something that disappears after four seconds.
 */
export function Toaster(props: ToasterProps) {
  const { resolvedTheme } = useTheme();

  return (
    <Sonner
      theme={(resolvedTheme as ToasterProps["theme"]) ?? "system"}
      position="bottom-right"
      // Long enough to read a sentence about a regulated action, and it pauses
      // on hover, so this is a floor rather than a deadline.
      duration={5000}
      closeButton
      toastOptions={{
        classNames: {
          toast:
            "group rounded-xl border bg-popover text-popover-foreground shadow-e3",
          description: "text-muted-foreground",
          actionButton: "bg-primary text-primary-foreground",
          cancelButton: "bg-muted text-muted-foreground",
          success: "border-success-border",
          warning: "border-warning-border",
          error: "border-danger-border",
        },
      }}
      {...props}
    />
  );
}
