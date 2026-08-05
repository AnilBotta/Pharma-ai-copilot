"use client";

import { CheckCircle2, CircleDashed, Loader2, XCircle } from "lucide-react";

import { AGENT_REGISTRY, getAgent } from "@/lib/agents";
import { cn } from "@/lib/utils";
import type { RunEvent } from "@/lib/api";

/**
 * Per-agent status derived from real run events.
 *
 * This replaces the prototype's `AgentRunLoader`, which stepped through a
 * hardcoded list of strings on a `setTimeout` and reported counts nobody had
 * computed. Every state here comes from an event the worker actually recorded.
 */

type AgentState = "pending" | "running" | "completed" | "failed";

const NODE_TO_AGENT: Record<string, string> = {
  intake_and_scope: "supervisor",
  supervisor_planner: "supervisor",
  research_agent: "research_agent",
  literature_agent: "literature_agent",
  patent_agent: "patent_agent",
  development_strategy_agent: "development_strategy_agent",
  evidence_reviewer: "evidence_reviewer",
  supervisor_synthesis: "supervisor",
  report_generation: "supervisor",
};

export function deriveAgentStates(events: RunEvent[]): Record<string, AgentState> {
  const states: Record<string, AgentState> = {};
  for (const agent of AGENT_REGISTRY) states[agent.id] = "pending";

  for (const event of events) {
    const agentId =
      event.agent_id ?? (event.node ? NODE_TO_AGENT[event.node] : undefined);
    if (!agentId || !(agentId in states)) continue;

    if (event.event_type === "node_started") states[agentId] = "running";
    else if (event.event_type === "node_completed") states[agentId] = "completed";
    else if (event.event_type === "node_failed") states[agentId] = "failed";
  }
  return states;
}

export function AgentTimeline({ events }: { events: RunEvent[] }) {
  const states = deriveAgentStates(events);

  return (
    <ul className="space-y-3">
      {AGENT_REGISTRY.map((agent) => {
        const state = states[agent.id];
        const Icon = agent.icon;
        const lastMessage = [...events]
          .reverse()
          .find(
            (e) =>
              (e.agent_id ?? (e.node ? NODE_TO_AGENT[e.node] : undefined)) ===
              agent.id
          );

        return (
          <li key={agent.id} className="flex items-start gap-3">
            <div
              className={cn(
                "mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border",
                state === "completed" && "border-emerald-500/30 bg-emerald-500/10",
                state === "running" && "border-blue-500/30 bg-blue-500/10",
                state === "failed" && "border-destructive/30 bg-destructive/10",
                state === "pending" && "border-border bg-muted/40"
              )}
            >
              <Icon
                className={cn(
                  "size-4",
                  state === "pending" ? "text-muted-foreground/50" : agent.color
                )}
              />
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <p
                  className={cn(
                    "text-sm font-medium",
                    state === "pending" && "text-muted-foreground"
                  )}
                >
                  {agent.name}
                </p>
                <StateIcon state={state} />
              </div>
              <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                {lastMessage?.message ?? agent.description}
              </p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function StateIcon({ state }: { state: AgentState }) {
  if (state === "completed")
    return <CheckCircle2 className="size-3.5 text-emerald-600 dark:text-emerald-400" />;
  if (state === "running")
    return <Loader2 className="size-3.5 animate-spin text-blue-600 dark:text-blue-400" />;
  if (state === "failed") return <XCircle className="size-3.5 text-destructive" />;
  return <CircleDashed className="size-3.5 text-muted-foreground/40" />;
}

export { getAgent };
