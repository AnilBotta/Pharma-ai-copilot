"use client";

import { motion } from "framer-motion";
import { Check, Copy, RotateCw } from "lucide-react";
import { useState } from "react";

import { CitationChip } from "@/components/chat/citation-chip";
import { LightMarkdown } from "@/components/chat/light-markdown";
import { useAuth } from "@/components/auth-provider";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/lib/types";

export function MessageBubble({
  message,
  streaming = false,
  onRegenerate,
}: {
  message: ChatMessage;
  streaming?: boolean;
  onRegenerate?: () => void;
}) {
  const { user } = useAuth();
  const [copied, setCopied] = useState(false);
  const isUser = message.role === "user";

  async function copyMessage() {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {}
  }

  if (isUser) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
        className="flex justify-end gap-3"
      >
        <div className="max-w-[78%] rounded-2xl rounded-br-md bg-gradient-to-br from-blue-600 to-indigo-600 px-4 py-3 text-sm text-white shadow-lg shadow-blue-600/20">
          <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>
        </div>
        <Avatar className="mt-0.5 size-7">
          <AvatarFallback className={cn(user.avatarColor, "text-[10px] text-white")}>
            {user.initials}
          </AvatarFallback>
        </Avatar>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
      className="flex gap-3"
    >
      <div className="relative mt-0.5 shrink-0">
        <div className="flex size-7 items-center justify-center rounded-lg border border-blue-500/25 bg-gradient-to-br from-blue-600/15 to-violet-600/15 text-blue-600 dark:text-blue-400">
          <svg viewBox="0 0 24 24" fill="none" className="size-4">
            <path
              d="M4 14a4 4 0 1 0 3.47-3.97A6.5 6.5 0 1 1 15.5 17.5a4 4 0 1 0-4.4-2.55L7.47 11.3A4 4 0 0 0 4 14Z"
              fill="currentColor"
            />
          </svg>
        </div>
      </div>

      <div className="max-w-[85%] space-y-3">
        <div className="rounded-2xl rounded-tl-md border bg-card/80 px-4 py-3.5 shadow-sm">
          <div className="mb-2 flex items-center gap-2">
            <span className="text-xs font-semibold">Pharma AI Copilot</span>
            <span className="rounded-full bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
              {streaming ? "Generating…" : "Grounded"}
            </span>
          </div>
          <div className="text-sm text-card-foreground">
            <LightMarkdown content={message.content} />
          </div>
        </div>

        {message.citations && message.citations.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {message.citations.map((c) => (
              <CitationChip key={c.id} citation={c} />
            ))}
          </div>
        )}

        {!streaming && (
          <div className="flex items-center gap-1 pl-1">
            <button
              onClick={copyMessage}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              {copied ? <Check className="size-3 text-emerald-500" /> : <Copy className="size-3" />}
              {copied ? "Copied" : "Copy"}
            </button>
            {onRegenerate && (
              <button
                onClick={onRegenerate}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                <RotateCw className="size-3" /> Regenerate
              </button>
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
}

export function TypingIndicator() {
  return (
    <div className="flex gap-3">
      <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg border border-blue-500/25 bg-gradient-to-br from-blue-600/15 to-violet-600/15 text-blue-600 dark:text-blue-400">
        <svg viewBox="0 0 24 24" fill="none" className="size-4">
          <path
            d="M4 14a4 4 0 1 0 3.47-3.97A6.5 6.5 0 1 1 15.5 17.5a4 4 0 1 0-4.4-2.55L7.47 11.3A4 4 0 0 0 4 14Z"
            fill="currentColor"
          />
        </svg>
      </div>
      <div className="flex items-center gap-1 rounded-2xl rounded-tl-md border bg-card/80 px-4 py-3.5">
        <span className="typing-dot size-1.5 rounded-full bg-muted-foreground" />
        <span className="typing-dot size-1.5 rounded-full bg-muted-foreground" />
        <span className="typing-dot size-1.5 rounded-full bg-muted-foreground" />
      </div>
    </div>
  );
}