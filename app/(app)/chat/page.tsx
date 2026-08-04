"use client";

import * as React from "react";
import { motion } from "framer-motion";
import {
  Download,
  MessageSquare,
  MessageSquarePlus,
  MoreHorizontal,
  Search,
  Sparkles,
} from "lucide-react";

import { ChatComposer } from "@/components/chat/chat-composer";
import { MessageBubble, TypingIndicator } from "@/components/chat/message-bubble";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn, downloadFile, formatRelative } from "@/lib/utils";
import { seedConversations, suggestedPrompts } from "@/lib/data";
import { conversationToMarkdown, generateMockResponse } from "@/lib/responses";
import type { ChatMessage, Conversation } from "@/lib/types";

export default function ChatPage() {
  const [conversations, setConversations] = React.useState<Conversation[]>(seedConversations);
  const [activeId, setActiveId] = React.useState<string>(seedConversations[0].id);
  const [search, setSearch] = React.useState("");
  const [streaming, setStreaming] = React.useState(false);
  const [phase, setPhase] = React.useState<"idle" | "thinking" | "streaming">("idle");

  const active = conversations.find((c) => c.id === activeId) ?? conversations[0];
  const scrollRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const viewport = scrollRef.current?.closest<HTMLElement>(
      "[data-slot='scroll-area-viewport']"
    );
    if (viewport) {
      viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
    }
  }, [active.messages.length, phase]);

  const filtered = conversations.filter((c) =>
    c.title.toLowerCase().includes(search.toLowerCase())
  );

  function newChat() {
    const conv: Conversation = {
      id: `c-${Date.now()}`,
      title: "New research thread",
      project: "ObesiScreen — Long-Acting GLP-1",
      messages: [],
      updated: new Date().toISOString(),
    };
    setConversations((prev) => [conv, ...prev]);
    setActiveId(conv.id);
  }

  function updateActive(update: (conv: Conversation) => Conversation) {
    setConversations((prev) => prev.map((c) => (c.id === activeId ? update(c) : c)));
  }

  async function handleSend(text: string) {
    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
    };

    updateActive((c) => ({
      ...c,
      title: c.title === "New research thread" ? text.slice(0, 40) : c.title,
      messages: [...c.messages, userMsg],
      updated: new Date().toISOString(),
    }));

    setStreaming(true);
    setPhase("thinking");
    await new Promise((r) => setTimeout(r, 700));

    const mock = generateMockResponse(text);
    setPhase("streaming");

    const assistantId = `a-${Date.now()}`;
    updateActive((c) => ({
      ...c,
      messages: [
        ...c.messages,
        { id: assistantId, role: "assistant", content: "", timestamp: new Date().toISOString() },
      ],
      updated: new Date().toISOString(),
    }));

    // Simulated token streaming
    const chunks = mock.content.match(/[\s\S]{1,6}/g) ?? [];
    let idx = 0;
    await new Promise<void>((resolve) => {
      const interval = setInterval(() => {
        if (idx >= chunks.length) {
          clearInterval(interval);
          updateActive((c) => ({
            ...c,
            messages: c.messages.map((m) =>
              m.id === assistantId ? { ...m, content: mock.content, citations: mock.citations } : m
            ),
          }));
          setPhase("idle");
          setStreaming(false);
          resolve();
          return;
        }
        const slice = chunks.slice(0, idx + 1).join("");
        idx += 1;
        updateActive((c) => ({
          ...c,
          messages: c.messages.map((m) => (m.id === assistantId ? { ...m, content: slice } : m)),
        }));
      }, 24);
    });
  }

  function handleExport() {
    const md = conversationToMarkdown(active);
    downloadFile(
      `${active.title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.md`,
      md,
      "text/markdown"
    );
  }

  function handleRegenerate() {
    const lastUser = [...active.messages].reverse().find((m) => m.role === "user");
    if (lastUser) void handleSend(lastUser.content);
  }

  return (
    <div className="flex h-[calc(100vh-8.5rem)] supports-[height:100dvh]:h-[calc(100dvh-8.5rem)] flex-col overflow-hidden rounded-2xl border bg-card/60 shadow-sm">
      <div className="flex h-full">
        {/* History panel */}
        <aside className="no-print hidden w-64 shrink-0 flex-col border-r lg:flex">
          <div className="p-3">
            <Button className="w-full justify-start gap-2" onClick={newChat}>
              <MessageSquarePlus className="size-4" />
              New chat
            </Button>
            <div className="relative mt-3">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search chats…"
                className="h-8 pl-8 text-xs"
              />
            </div>
          </div>
          <ScrollArea className="min-h-0 flex-1 border-t">
            <div className="space-y-0.5 p-2">
              {filtered.map((conv) => (
                <button
                  key={conv.id}
                  onClick={() => setActiveId(conv.id)}
                  className={cn(
                    "flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left transition-colors",
                    conv.id === activeId
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground"
                  )}
                >
                  <MessageSquare
                    className={cn("mt-0.5 size-3.5 shrink-0", conv.id === activeId && "text-primary")}
                  />
                  <div className="min-w-0 flex-1">
                    <p
                      className={cn(
                        "truncate text-[13px] font-medium",
                        conv.id === activeId && "text-primary"
                      )}
                    >
                      {conv.title}
                    </p>
                    <p className="mt-0.5 truncate text-[11px] text-muted-foreground/70">
                      {conv.messages.length} messages · {formatRelative(conv.updated)}
                    </p>
                  </div>
                </button>
              ))}
              {filtered.length === 0 && (
                <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                  No conversations found
                </p>
              )}
            </div>
          </ScrollArea>
        </aside>

        {/* Message panel */}
        <div className="relative flex min-w-0 flex-1 flex-col">
          {/* Header */}
          <div className="no-print flex h-12 shrink-0 items-center justify-between gap-2 border-b px-4">
            <div className="flex min-w-0 items-center gap-2">
              <MessageSquare className="size-4 shrink-0 text-blue-600 dark:text-blue-400" />
              <p className="truncate text-sm font-medium">{active.title}</p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <Button
                variant="outline"
                size="sm"
                className="h-7 gap-1.5 text-xs"
                onClick={handleExport}
                disabled={active.messages.length === 0}
              >
                <Download className="size-3.5" /> Export
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon-sm" aria-label="More options">
                    <MoreHorizontal className="size-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={handleExport}>Export conversation (Markdown)</DropdownMenuItem>
                  <DropdownMenuItem onClick={newChat}>Start new chat</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>

          {/* Messages */}
          <ScrollArea className="min-h-0 flex-1">
            <div ref={scrollRef} className="mx-auto max-w-3xl space-y-5 px-4 py-6">
              {active.messages.length === 0 && phase === "idle" ? (
                <div className="flex h-full flex-col items-center justify-center gap-6 py-10">
                  <motion.div
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ duration: 0.5 }}
                    className="flex flex-col items-center text-center"
                  >
                    <div className="relative">
                      <div className="absolute inset-0 animate-pulse-ring rounded-2xl bg-blue-500/20" />
                      <div className="relative flex size-14 items-center justify-center rounded-2xl border border-blue-500/25 bg-gradient-to-br from-blue-600/15 to-violet-600/15 text-blue-600 dark:text-blue-400">
                        <Sparkles className="size-7" />
                      </div>
                    </div>
                    <h2 className="mt-4 text-lg font-semibold tracking-tight">Research Copilot</h2>
                    <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                      Grounded in your patents, literature and internal documents. Every answer
                      carries citations you can verify.
                    </p>
                  </motion.div>

                  <div className="no-print grid w-full max-w-xl gap-2.5 sm:grid-cols-2">
                    {suggestedPrompts.map((prompt, i) => (
                      <motion.button
                        key={prompt}
                        initial={{ opacity: 0, y: 12 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.1 + i * 0.06 }}
                        onClick={() => handleSend(prompt)}
                        className="group rounded-xl border bg-card/70 p-3.5 text-left transition-all hover:-translate-y-0.5 hover:border-blue-500/40 hover:shadow-lg hover:shadow-blue-900/10"
                      >
                        <Sparkles className="size-4 text-blue-600 dark:text-blue-400" />
                        <p className="mt-2 text-[13px] font-medium leading-snug">{prompt}</p>
                      </motion.button>
                    ))}
                  </div>
                </div>
              ) : (
                <>
                  {active.messages.map((m) => (
                    <MessageBubble
                      key={m.id}
                      message={m}
                      streaming={
                        phase === "streaming" && m.id === active.messages[active.messages.length - 1]?.id
                      }
                      onRegenerate={handleRegenerate}
                    />
                  ))}
                  {phase === "thinking" && <TypingIndicator />}
                </>
              )}
            </div>
          </ScrollArea>

          {/* Composer */}
          <div className="no-print shrink-0 border-t p-3">
            <div className="mx-auto max-w-3xl">
              <ChatComposer onSend={handleSend} disabled={streaming} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}