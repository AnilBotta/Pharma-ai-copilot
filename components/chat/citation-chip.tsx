"use client";

import { BookOpen, Check, Copy } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { Citation } from "@/lib/types";

export function CitationChip({ citation }: { citation: Citation }) {
  const [copied, setCopied] = useState(false);

  async function copyDoi() {
    try {
      await navigator.clipboard.writeText(citation.title);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {}
  }

  return (
    <div className="group flex items-center gap-2.5 rounded-lg border bg-card/70 px-3 py-2 text-xs transition-colors hover:border-blue-500/40">
      <BookOpen className="size-3.5 shrink-0 text-blue-600 dark:text-blue-400" />
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">{citation.title}</p>
        <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
          {citation.source} · {citation.year}
        </p>
      </div>
      <Badge variant="secondary" className="hidden shrink-0 px-1.5 py-0 text-[10px] sm:inline-flex">
        {citation.type}
      </Badge>
      <button
        onClick={copyDoi}
        className={cn(
          "shrink-0 rounded p-1 text-muted-foreground opacity-0 transition-all hover:bg-accent hover:text-foreground group-hover:opacity-100",
          copied && "opacity-100 text-emerald-500"
        )}
        aria-label="Copy citation"
      >
        {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
      </button>
    </div>
  );
}