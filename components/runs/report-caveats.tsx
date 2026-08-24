"use client";

import * as React from "react";
import { ChevronDown, Info } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The run-level caveats, collapsed.
 *
 * Measured on a real completed run: eleven warnings rendered a 1,378px amber
 * slab, and the first line of the report itself did not appear until 1,778px
 * down the page — two full screens of caveats before a word of the thing
 * anybody opened the page to read.
 *
 * Collapsing them is not hiding them. The count and the amber are in the
 * summary, it is one click to open, and — the change that matters — they now
 * PRINT. They were `no-print` before, so a report circulated to an auditor
 * arrived without the sentences saying "no external literature was consulted".
 * Understating a report's confidence is the safe direction to be wrong in;
 * silently dropping its qualifications is not.
 */
export function ReportCaveats({ warnings }: { warnings: string[] }) {
  const [open, setOpen] = React.useState(false);

  if (warnings.length === 0) return null;

  return (
    <div className="rounded-xl border border-warning-border bg-warning-surface print:break-inside-avoid">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3 text-left outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
      >
        <Info aria-hidden="true" className="size-4 shrink-0 text-warning" />
        <span className="flex-1 text-sm font-medium text-warning">
          {warnings.length} caveat{warnings.length === 1 ? "" : "s"} on how this
          report should be read
        </span>
        <ChevronDown
          aria-hidden="true"
          className={cn(
            "size-4 shrink-0 text-warning transition-transform print:hidden",
            open && "rotate-180"
          )}
        />
      </button>

      {/* `print:block` rather than `print:!block`: the collapsed state is a
          screen affordance, and paper has no affordances. */}
      <ul
        className={cn(
          "space-y-2 px-4 pb-4 pl-11 text-sm text-muted-foreground",
          open ? "block" : "hidden print:block"
        )}
      >
        {warnings.map((warning, i) => (
          <li key={i} className="list-disc marker:text-warning">
            {warning}
          </li>
        ))}
      </ul>
    </div>
  );
}
