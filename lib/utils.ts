import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

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
