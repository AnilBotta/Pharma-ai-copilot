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
  PencilLine,
  Play,
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
import { ProposalCard } from "@/components/manager/proposal-card";
import { useManager } from "@/components/manager/manager-provider";
import { LightMarkdown } from "@/components/chat/light-markdown";
import {
  ApiError,
  pdp,
  streamManagerTurn,
  type AgentProposal,
  type ManagerMessage,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/** What each tool is doing, in words a director would use. */
const TOOL_LABEL: Record<string, string> = {
  list_projects: "Listing projects",
  list_programmes: "Reading the portfolio",
  get_programme: "Opening the programme",
  get_gate: "Reading the gate",
  get_blockers: "Finding what is blocking each gate",
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
  // Dispatch. Worded so a reader can tell work was STARTED, not just read.
  list_people: "Looking up who is on the programme",
  assess_gate: "Asking the Operations Agent to analyse the gate",
  start_research_run: "Starting a research run",
  sweep_notifications: "Recomputing alerts",
  // Writes. Worded in the past tense: by the time the trail settles these have
  // already happened, and a reader must not mistake them for intentions.
  create_task: "Created a task",
  update_task: "Updated a task",
  add_task_dependency: "Linked two tasks",
  create_milestone: "Added a milestone",
  set_assignment: "Changed an assignment",
  set_blocked: "Changed a blocked state",
  acknowledge_notification: "Acknowledged an alert",
  create_document: "Registered a document",
  propose: "Prepared something for you to confirm",
};

/** Tools that set work in motion rather than reading. Marked in the trail. */
const DISPATCH_TOOLS = new Set([
  "assess_gate",
  "start_research_run",
  "sweep_notifications",
]);

/**
 * Tools that changed the record.
 *
 * Called out more strongly than dispatch: starting a job is something you can
 * wait out, but an edit to somebody's plan has already happened by the time
 * you read the line, and the reader's next question is "what did it touch".
 */
const WRITE_TOOLS = new Set([
  "create_task",
  "update_task",
  "add_task_dependency",
  "create_milestone",
  "set_assignment",
  "set_blocked",
  "acknowledge_notification",
  "create_document",
]);

interface Activity {
  name: string;
  done: boolean;
  ok: boolean;
}

/**
 * A message plus the reading that produced it.
 *
 * The trail belongs to its turn, not to the panel. Held separately it renders
 * after the answer and lingers there once the turn is over - which reverses the
 * order of events and, worse, leaves the previous question's reading sitting
 * under the current answer as though it were evidence for it.
 */
interface PanelMessage extends ManagerMessage {
  activity?: Activity[];
}

export function ManagerPanel() {
  const { open, closeManager, seed, clearSeed } = useManager();

  const [conversationId, setConversationId] = React.useState<string | null>(null);
  const [messages, setMessages] = React.useState<PanelMessage[]>([]);
  const [draft, setDraft] = React.useState("");
  const [streaming, setStreaming] = React.useState(false);
  const [partial, setPartial] = React.useState("");
  const [activity, setActivity] = React.useState<Activity[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [proposals, setProposals] = React.useState<AgentProposal[]>([]);

  // Refetched rather than pushed down the stream. A proposal outlives the turn
  // that made it — it is still waiting after a reload, and the panel showing
  // it only in the session that produced it would be a way to lose one.
  const refreshProposals = React.useCallback(async () => {
    try {
      setProposals(await pdp.listProposals());
    } catch {
      // Not worth surfacing: the answer is the thing being read, and a failed
      // proposal fetch does not make it wrong.
    }
  }, []);

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
      // Collected here as well as in state: the committed message needs the
      // final list, and reading it out of a setState closure would race.
      const trail: Activity[] = [];

      try {
        const id = await ensureConversation();
        for await (const event of streamManagerTurn(id, content, controller.signal)) {
          if (event.type === "token") {
            answer += event.text;
            setPartial(answer);
          } else if (event.type === "tool_started") {
            trail.push({ name: event.name, done: false, ok: true });
            setActivity([...trail]);
          } else if (event.type === "tool_finished") {
            const pending = trail.find((a) => a.name === event.name && !a.done);
            if (pending) {
              pending.done = true;
              pending.ok = event.ok;
            }
            setActivity([...trail]);
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
              activity: trail.length ? [...trail] : undefined,
            },
          ]);
        }
        setPartial("");
        // The trail moves onto the message it produced; leaving a copy here
        // would show it twice, and once in the wrong place.
        setActivity([]);
        setStreaming(false);
        abortRef.current = null;
        void refreshProposals();
      }
    },
    [ensureConversation, streaming, refreshProposals]
  );

  React.useEffect(() => {
    if (open) void refreshProposals();
  }, [open, refreshProposals]);

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
          <SheetTitle className="flex items-center gap-2.5">
            <span className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-primary/15 bg-primary/8 text-primary">
              <Bot aria-hidden="true" className="size-4" />
            </span>
            Manager Agent
          </SheetTitle>
          {/* The limits are the product, so they are stated where the agent is
              introduced rather than discovered when a button does nothing. */}
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

          {/* Only while the turn is running. Once it finishes the trail is
              carried by the message it produced, above that answer. */}
          {streaming && activity.length > 0 && (
            <ActivityTrail activity={activity} />
          )}

          {/* The caret is the only thing that distinguishes "still writing"
              from "stopped mid-sentence", and a partial answer is exactly
              where that distinction matters. */}
          {partial && (
            <div className="text-sm">
              <LightMarkdown content={partial} />
              <span
                aria-hidden="true"
                className="mt-1 inline-block h-3.5 w-[2px] animate-pulse bg-primary align-text-bottom"
              />
              <span className="sr-only">Still writing.</span>
            </div>
          )}

          {streaming && !partial && activity.length === 0 && (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 aria-hidden="true" className="size-3.5 animate-spin" />{" "}
              Thinking…
            </p>
          )}

          {error && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-lg border border-danger-border bg-danger-surface p-3 text-xs text-danger"
            >
              <AlertTriangle aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
              <p>{error}</p>
            </div>
          )}

          {/* Below the answer, because it is the consequence of it — and
              because a decision control should never be the first thing the
              eye lands on. */}
          {proposals.map((p) => (
            <ProposalCard key={p.id} proposal={p} onSettled={refreshProposals} />
          ))}

          <div ref={bottomRef} />
        </div>

        <div className="border-t bg-card p-3">
          <div className="flex items-end gap-2">
            <Textarea
              rows={2}
              value={draft}
              disabled={streaming}
              aria-label="Ask the Manager Agent"
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

function MessageBubble({ message }: { message: PanelMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-xl rounded-br-sm bg-primary/10 px-3.5 py-2 text-sm">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {/* What it read, above what it concluded - the order it happened in,
          and the order you need them in to judge the second by the first. */}
      {message.activity && message.activity.length > 0 && (
        <ActivityTrail activity={message.activity} />
      )}
      {/* Was `whitespace-pre-wrap`. Seven of sixteen stored answers are
          markdown lists, so the reader was being shown literal "- " and the
          two-space indents of the nested ones. */}
      {message.content && (
        <div className="text-sm">
          <LightMarkdown content={message.content} />
        </div>
      )}
      {message.truncated && (
        <div className="rounded-lg border border-warning-border bg-warning-surface p-2.5 text-xs text-warning">
          <span className="font-medium">This answer is incomplete.</span>{" "}
          {message.truncated_reason}
        </div>
      )}
    </div>
  );
}

function ActivityTrail({ activity }: { activity: Activity[] }) {
  // Deliberately NOT collapsible. This module exists on the premise that tool
  // activity is shown rather than hidden, so the trail is made scannable
  // instead — reads recede, writes and dispatches carry a rail and hold full
  // contrast, and the eye can find "it changed something" without reading
  // every line.
  return (
    <div className="rounded-lg border bg-muted/30 px-3 py-2.5">
      <p className="type-label mb-1.5 text-muted-foreground">What it did</p>
      <div className="space-y-1">
        {activity.map((a, i) => {
          const dispatched = DISPATCH_TOOLS.has(a.name);
          const wrote = WRITE_TOOLS.has(a.name);
          const failed = a.done && !a.ok;
          return (
            <p
              key={`${a.name}-${i}`}
              className={cn(
                "flex items-center gap-2 text-xs",
                a.done ? "text-muted-foreground" : "text-foreground",
                (dispatched || wrote) &&
                  "-ml-3 border-l-2 pl-[10px] font-medium text-foreground",
                wrote && "border-warning-solid",
                dispatched && "border-primary",
                // Amber, not red, and that is the original author's call kept
                // deliberately: the turn still produced an answer, it just
                // rests on less than it should. That is a caveat, not a fault.
                failed && "text-warning"
              )}
            >
              {a.done ? (
                a.ok ? (
                  wrote ? (
                    <PencilLine
                      aria-hidden="true"
                      className="size-3 shrink-0 text-warning"
                    />
                  ) : dispatched ? (
                    <Play aria-hidden="true" className="size-3 shrink-0 text-primary" />
                  ) : (
                    <Check aria-hidden="true" className="size-3 shrink-0 text-success" />
                  )
                ) : (
                  <AlertTriangle
                    aria-hidden="true"
                    className="size-3 shrink-0 text-warning"
                  />
                )
              ) : (
                <Loader2 aria-hidden="true" className="size-3 shrink-0 animate-spin" />
              )}
              <span className="min-w-0">
                {TOOL_LABEL[a.name] ?? a.name}
                {failed && " — could not be completed"}
              </span>
            </p>
          );
        })}
      </div>
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
      <p className="type-label text-muted-foreground">Try asking</p>
      {SUGGESTIONS.map((s) => (
        <button
          key={s}
          type="button"
          onClick={() => onPick(s)}
          className="group flex w-full items-center gap-2.5 rounded-lg border bg-card px-3 py-2.5 text-left text-xs transition-colors outline-none hover:border-primary/40 hover:bg-accent focus-visible:border-primary/40 focus-visible:bg-accent"
        >
          <Search
            aria-hidden="true"
            className="size-3.5 shrink-0 text-muted-foreground transition-colors group-hover:text-primary"
          />
          <span className="min-w-0">{s}</span>
        </button>
      ))}
      <p className="pt-1 text-2xs text-muted-foreground">
        Or ask anything about your programmes, or about how this system works.
      </p>
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
