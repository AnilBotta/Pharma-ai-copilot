import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * tailwind-merge has to be told about scale steps we added ourselves,
 * because it decides which classes conflict by matching them against its own
 * built-in scales rather than reading our CSS.
 *
 * The elevation steps are the ones that were actually broken. Measured
 * against bare `twMerge` before this change:
 *
 *   "shadow-e2 shadow-primary/20"  ->  "shadow-primary/20"   // e2 dropped
 *   "shadow-sm shadow-e2"          ->  "shadow-sm shadow-e2" // no override
 *
 * `shadow-e2` looked like a shadow *colour*, so it was discarded by a real
 * colour; and it was not recognised as a shadow *size*, so it could not
 * override `shadow-sm`. Both fail silently — a component keeps its old
 * elevation and nothing warns.
 *
 * The font-size steps are registered defensively rather than to fix a bug:
 * `text-2xs` and `text-md` were checked and already merged correctly, but
 * that is incidental behaviour we would rather not depend on. Pinned by
 * lib/utils.test.ts, which records the measured before/after either way.
 */
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: ["2xs", "md"] }],
      shadow: [{ shadow: ["e1", "e2", "e3", "e4"] }],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(input: string | Date, opts: Intl.DateTimeFormatOptions = {}) {
  const date = typeof input === "string" ? new Date(input) : input;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    ...opts,
  }).format(date);
}

export function formatRelative(input: string | Date) {
  const date = typeof input === "string" ? new Date(input) : input;
  const diff = Date.now() - date.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return formatDate(date);
}

/** Render a graph node name for display: "literature_agent" -> "Literature agent". */
export function humanNode(node: string) {
  return node.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function maskApiKey(key: string) {
  if (key.length <= 10) return key;
  return `${key.slice(0, 7)}${"•".repeat(12)}${key.slice(-4)}`;
}

export function downloadFile(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
