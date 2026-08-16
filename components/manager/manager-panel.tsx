"use client";

/**
 * The Manager Agent chat.
 *
 * TWO THINGS THIS UI HAS TO GET RIGHT
 *
 * Tool activity is shown, not hidden. A turn that reads four tables before
 * answering takes half a minute, and a spinner for thirty seconds reads as
 * broken. It also matters for a reason beyond patience: seeing that the agent
 * read `get_gate` is what lets a reader judge whether the answer rests on
 * anything. An assistant that silently produces confident prose is exactly the
 * thing this system is built not to be.
 *
 * A truncated turn never looks finished. `truncated` is stored on the message,
 * so an answer cut short by the time or token budget still says so after a
 * reload - not only in the session that produced it.
 */

import * as React from "react";
import {
  AlertTriangle,
  Bot,
  Check,
  Loader2,
  Plus,
  Search,
  SendHorizonal,
} from "lucide-react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useManager } from "@/components/manager/manager-provider";
import {
  ApiError,
  pdp,
  streamManagerTurn,
  type ManagerMessage,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/** What each tool is doing, in words a director would use. */
const TOOL_LABEL: Record<string, string> = {
  list_projects: "Listing projects",
  list_programmes: "Reading the portfolio",
  get_programme: "Opening the programme",
  get_gate: "Reading the gate",
  get_requirement: "Reading a requirement",
  get_schedule: "Checking the schedule",
  list_documents: "Checking the document register",
  get_document: "Reading a document",
  list_notifications: "Checking open alerts",
  project_audit: "Reading the audit trail",
  list_agent_sessions: "Reading previous agent runs",
  list_runs: "Listing research runs",
  get_run_report: "Reading a research report",
  search_docs: "Consulting the documentation",
};

interface Activity {
  name: string;
  done: boolean;
  ok: boolean;
}

export function ManagerPanel() {
  const { open, closeManager, seed, clearSeed } = useManager();

  const [conversationId, setConversationId] = React.useState<string | null>(null);
  const [messages, setMessages] = React.useState<ManagerMessage[]>([]);
  const [draft, setDraft] = React.useState("");
  const [streaming, setStreaming] = React.useState(false);
  const [partial, setPartial] = React.useState("");
  const [activity, setActivity] = React.useState<Activity[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  const bottomRef = React.useRef<HTMLDivElement>(null);
  const abortRef = React.useRef<AbortController | null>(null);

  const scrollToBottom = React.useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, []);

  React.useEffect(() => {
    if (open) scrollToBottom();
  }, [open, messages, partial, activity, scrollToBottom]);

  // Abandon an in-flight turn if the panel unmounts; otherwise the reader keeps
  // consuming a stream nothing is displaying.
  React.useEffect(() => () => abortRef.current?.abort(), []);

  const ensureConversation = React.useCallback(async (): Promise<string> => {
    if (conversationId) return conversationId;
    const created = await pdp.createConversation();
    setConversationId(created.id);
    return created.id;
  }, [conversationId]);

  const send = React.useCallback(
    async (text: string) => {
      const content = text.trim();
      if (!content || streaming) return;

      setError(null);
      setDraft("");
      setStreaming(true);
      setPartial("");
      setActivity([]);

      // Shown immediately with a provisional id. The server persists the real
      // row; this is only so the question does not vanish while we wait.
      setMessages((prev) => [
        ...prev,
        {
          id: -Date.now(),
          role: "user",
          content,
          tool_name: null,
          tool_arguments: null,
          truncated: false,
          truncated_reason: null,
          created_at: new Date().toISOString(),
        },
      ]);

      const controller = new AbortController();
      abortRef.current = controller;
      let answer = "";
      let truncatedReason: string | null = null;

      try {
        const id = await ensureConversation();
        for await (const event of streamManagerTurn(id, content, controller.signal)) {
          if (event.type === "token") {
            answer += event.text;
            setPartial(answer);
          } else if (event.type === "tool_started") {
            setActivity((prev) => [
              ...prev,
              { name: event.name, done: false, ok: true },
            ]);
          } else if (event.type === "tool_finished") {
            setActivity((prev) =>
              prev.map((a) =>
                a.name === event.name && !a.done
                  ? { ...a, done: true, ok: event.ok }
                  : a
              )
            );
          } else if (event.type === "truncated") {
            truncatedReason = event.detail;
          } else if (event.type === "error") {
            setError(event.message);
          }
        }
      } catch (err) {
        if (!controller.signal.aborted) {
          setError(err instanceof ApiError ? err.message : String(err));
        }
      } finally {
        if (answer || truncatedReason) {
          setMessages((prev) => [
            ...prev,
            {
              id: -Date.now(),
              role: "assistant",
              content: answer,
              tool_name: null,
              tool_arguments: null,
              truncated: truncatedReason !== null,
              truncated_reason: truncatedReason,
              created_at: new Date().toISOString(),
            },
          ]);
        }
        setPartial("");
        setStreaming(false);
        abortRef.current = null;
      }
    },
    [ensureConversation, streaming]
  );

  // A page can hand over a starting question. Fired once, then cleared.
  React.useEffect(() => {
    if (open && seed && !streaming) {
      const question = seed;
      clearSeed();
      void send(question);
    }
  }, [open, seed, streaming, clearSeed, send]);

  const startNew = async () => {
    abortRef.current?.abort();
    setConversationId(null);
    setMessages([]);
    setPartial("");
    setActivity([]);
    setError(null);
  };

  const resume = async (id: string) => {
    setLoading(true);
    try {
      const detail = await pdp.getConversation(id);
      setConversationId(detail.id);
      setMessages(detail.messages.filter((m) => m.role !== "tool"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Sheet open={open} onOpenChange={(next) => !next && closeManager()}>
      <SheetContent className="p-0">
        <SheetHeader className="pr-12">
          <SheetTitle className="flex items-center gap-2">
            <Bot className="size-4 text-muted-foreground" />
            Manager Agent
          </SheetTitle>
          <SheetDescription>
            Reads everything you can see. It cannot approve a requirement,
            decide a gate or move a baseline — those need a person.
          </SheetDescription>
        </SheetHeader>

        <div className="flex items-center gap-2 border-b px-5 py-2">
          <Button size="sm" variant="ghost" onClick={startNew} disabled={streaming}>
            <Plus className="size-3.5" /> New
          </Button>
          <ConversationPicker onPick={resume} disabled={streaming} />
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
          {messages.length === 0 && !streaming && !loading && (
            <Suggestions onPick={send} />
          )}

          {messages.map((m) => (
            <MessageBubble key={m.id} message={m} />
          ))}

          {activity.length > 0 && <ActivityTrail activity={activity} />}

          {partial && (
            <div className="text-sm whitespace-pre-wrap">{partial}</div>
          )}

          {streaming && !partial && activity.length === 0 && (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" /> Thinking…
            </p>
          )}

          {error && (
            <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
              <p>{error}</p>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        <div className="border-t p-3">
          <div className="flex items-end gap-2">
            <Textarea
              rows={2}
              value={draft}
              disabled={streaming}
              placeholder="Ask about your programmes…"
              className="resize-none"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send(draft);
                }
              }}
            />
            <Button
              size="icon"
              disabled={streaming || !draft.trim()}
              onClick={() => void send(draft)}
              aria-label="Send"
            >
              {streaming ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <SendHorizonal className="size-4" />
              )}
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function MessageBubble({ message }: { message: ManagerMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-lg bg-primary/10 px-3 py-2 text-sm">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {message.content && (
        <div className="text-sm whitespace-pre-wrap">{message.content}</div>
      )}
      {message.truncated && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-2.5 text-xs text-amber-800 dark:text-amber-300">
          <span className="font-medium">This answer is incomplete.</span>{" "}
          {message.truncated_reason}
        </div>
      )}
    </div>
  );
}

function ActivityTrail({ activity }: { activity: Activity[] }) {
  return (
    <div className="space-y-1 rounded-lg border bg-muted/30 px-3 py-2">
      {activity.map((a, i) => (
        <p
          key={`${a.name}-${i}`}
          className={cn(
            "flex items-center gap-2 text-xs",
            a.done ? "text-muted-foreground" : "text-foreground"
          )}
        >
          {a.done ? (
            a.ok ? (
              <Check className="size-3 text-emerald-600" />
            ) : (
              <AlertTriangle className="size-3 text-amber-600" />
            )
          ) : (
            <Loader2 className="size-3 animate-spin" />
          )}
          {TOOL_LABEL[a.name] ?? a.name}
          {a.done && !a.ok && " — could not be read"}
        </p>
      ))}
    </div>
  );
}

const SUGGESTIONS = [
  "Which gates cannot open, and why?",
  "What needs a decision from me this week?",
  "Which documents have lapsed or are about to?",
  "Why can a requirement's owner not approve it themselves?",
];

function Suggestions({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        Ask anything about your programmes, or about how this system works.
      </p>
      {SUGGESTIONS.map((s) => (
        <button
          key={s}
          type="button"
          onClick={() => onPick(s)}
          className="block w-full rounded-lg border px-3 py-2 text-left text-xs transition-colors hover:border-primary/40 hover:bg-accent"
        >
          {s}
        </button>
      ))}
    </div>
  );
}

function ConversationPicker({
  onPick,
  disabled,
}: {
  onPick: (id: string) => void;
  disabled: boolean;
}) {
  const [items, setItems] = React.useState<{ id: string; title: string }[]>([]);
  const [openList, setOpenList] = React.useState(false);

  const load = async () => {
    try {
      setItems(await pdp.listConversations());
      setOpenList((v) => !v);
    } catch {
      setItems([]);
    }
  };

  return (
    <div className="relative">
      <Button size="sm" variant="ghost" onClick={load} disabled={disabled}>
        <Search className="size-3.5" /> History
      </Button>
      {openList && items.length > 0 && (
        <div className="absolute z-10 mt-1 max-h-64 w-72 overflow-y-auto rounded-lg border bg-background p-1 shadow-lg">
          {items.map((c) => (
            <button
              key={c.id}
              type="button"
              className="block w-full truncate rounded px-2 py-1.5 text-left text-xs hover:bg-accent"
              onClick={() => {
                setOpenList(false);
                onPick(c.id);
              }}
            >
              {c.title}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
