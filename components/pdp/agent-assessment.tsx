"use client";

/**
 * The PDP Operations Agent's view of a gate.
 *
 * WHY THIS COMPONENT IS SHAPED THE WAY IT IS
 *
 * The module's whole purpose is that nothing reports a gate as better than it
 * is. An assessment written by a model is the most likely thing in the system
 * to do that by accident, so the presentation has three rules:
 *
 *  1. It never appears above the readiness engine's own figure, and never uses
 *     the same visual language. Readiness is a verdict; this is an opinion.
 *  2. Nothing here is persistent state. It is fetched on demand, shown, and
 *     forgotten - so nobody can mistake a stale assessment for current fact.
 *  3. The disclaimer is not fine print. A reader who takes only the headline
 *     away should still know a person has to decide.
 *
 * The button says "what is holding this up", not "assess readiness", because
 * the engine already answered readiness and a second answer would invite the
 * two to be compared.
 */

import * as React from "react";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  FlaskConical,
  Loader2,
  Sparkles,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ApiError, pdp, type GateAssessment } from "@/lib/api";
import { cn } from "@/lib/utils";

const URGENCY: Record<
  string,
  { label: string; variant: "destructive" | "warning" | "muted" }
> = {
  now: { label: "Now", variant: "destructive" },
  this_week: { label: "This week", variant: "warning" },
  when_convenient: { label: "When convenient", variant: "muted" },
};

export function AgentAssessment({
  stageId,
  blockerCount,
}: {
  stageId: string;
  blockerCount: number;
}) {
  const [result, setResult] = React.useState<GateAssessment | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      setResult(await pdp.assessGate(stageId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  // A gate with nothing outstanding has nothing to diagnose, and spending a
  // model call to be told so would teach people the feature is noise.
  if (blockerCount === 0 && !result) {
    return null;
  }

  return (
    <Card className="border-dashed">
      <CardContent className="space-y-4 py-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-sm font-medium">
              <Bot className="size-4 text-muted-foreground" />
              PDP Operations Agent
            </div>
            <p className="mt-1 max-w-prose text-xs text-muted-foreground">
              Reads this gate&rsquo;s record and says which blockers are the real
              constraint. It cannot approve a requirement, decide this gate or
              move a date — the database refuses it, not merely this screen.
            </p>
          </div>
          <Button size="sm" variant="outline" disabled={loading} onClick={run}>
            {loading ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Sparkles className="size-3.5" />
            )}
            {result ? "Ask again" : "What is holding this up?"}
          </Button>
        </div>

        {loading && (
          <p className="text-xs text-muted-foreground">
            Reading {blockerCount} outstanding requirement
            {blockerCount === 1 ? "" : "s"} and their evidence. This takes about
            a minute.
          </p>
        )}

        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-danger-border bg-danger-surface p-3 text-xs text-destructive">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
            <div>
              <p>{error}</p>
              <p className="mt-1 text-muted-foreground">
                The gate&rsquo;s readiness and blocker list above are unaffected
                and remain authoritative.
              </p>
            </div>
          </div>
        )}

        {result && <AssessmentBody result={result} />}
      </CardContent>
    </Card>
  );
}

function AssessmentBody({ result }: { result: GateAssessment }) {
  // Root causes first. The agent is asked to separate causes from
  // consequences precisely so this list can be short, and sorting by the
  // model's own distinction is the only way that answer reaches the reader.
  const analysis = [...result.blocker_analysis].sort(
    (a, b) => Number(b.is_root_cause) - Number(a.is_root_cause)
  );
  const rootCauses = analysis.filter((b) => b.is_root_cause).length;

  return (
    <div className="space-y-4 border-t pt-4">
      <p className="text-sm">{result.summary}</p>

      {analysis.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">
            {rootCauses > 0
              ? `${rootCauses} of ${analysis.length} identified as causes rather than consequences`
              : `${analysis.length} outstanding`}
          </p>
          {analysis.map((b) => (
            <div
              key={b.ref_code}
              className={cn(
                "rounded-lg border p-3 text-xs",
                b.is_root_cause && "border-warning-border bg-warning-surface"
              )}
            >
              <div className="flex flex-wrap items-center gap-2">
                <code className="font-mono text-muted-foreground">
                  {b.ref_code}
                </code>
                {b.is_root_cause ? (
                  <Badge variant="warning">Root cause</Badge>
                ) : (
                  <Badge variant="muted">Consequence</Badge>
                )}
                {b.obvious_action_would_not_help && (
                  <Badge variant="destructive">
                    The obvious action will not fix this
                  </Badge>
                )}
              </div>
              <p className="mt-1.5">{b.why_it_is_stuck}</p>
            </div>
          ))}
        </div>
      )}

      {result.recommended_actions.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">
            Suggested next steps — for a person to decide on, not instructions
          </p>
          {result.recommended_actions.map((a, i) => {
            const urgency = URGENCY[a.urgency] ?? URGENCY.this_week;
            return (
              <div
                key={`${a.ref_code ?? "general"}-${i}`}
                className="flex items-start gap-2.5 rounded-lg border px-3 py-2 text-xs"
              >
                <ArrowRight className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <p>{a.action}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-muted-foreground">
                    {a.ref_code && (
                      <code className="font-mono">{a.ref_code}</code>
                    )}
                    <span>{a.who}</span>
                    <Badge variant={urgency.variant}>{urgency.label}</Badge>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {result.handoff_question && (
        <div className="rounded-lg border border-info-border bg-info-surface p-3 text-xs">
          <div className="flex items-center gap-2 font-medium text-info">
            <FlaskConical className="size-3.5" />
            Referred to the Scientist Agent
          </div>
          <p className="mt-1.5">{result.handoff_question}</p>
          <p className="mt-1.5 text-muted-foreground">
            A project-management model should not rule on whether data is
            adequate. This question is recorded rather than answered.
          </p>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        Advisory. Nothing here changes this gate&rsquo;s readiness, and no part
        of it counts as an approval.
      </p>
    </div>
  );
}
