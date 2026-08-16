"use client";

/**
 * The Manager Agent's portfolio briefing.
 *
 * The failure mode this guards against is the opposite of the gate page's. A
 * portfolio view is where "89% complete across four programmes" gets said out
 * loud, and an average of readiness percentages is the single most misleading
 * number this system could produce - it hides the one programme that cannot
 * open its gate inside three that can.
 *
 * So this component shows no percentage at all. Each programme gets one line
 * of prose and a flag for whether somebody has to decide something. The cards
 * below it still carry the engine's own figures, which is where a number
 * belongs: attached to the gate it describes.
 */

import * as React from "react";
import { AlertTriangle, Bot, Loader2, Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ApiError, pdp, type PortfolioSummary } from "@/lib/api";

export function PortfolioBriefing({ programmeCount }: { programmeCount: number }) {
  const [result, setResult] = React.useState<PortfolioSummary | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      setResult(await pdp.portfolioSummary());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  if (programmeCount === 0) return null;

  return (
    <Card className="border-dashed">
      <CardContent className="space-y-4 py-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-sm font-medium">
              <Bot className="size-4 text-muted-foreground" />
              Manager Agent
            </div>
            <p className="mt-1 max-w-prose text-xs text-muted-foreground">
              What across these {programmeCount} programme
              {programmeCount === 1 ? "" : "s"} needs a decision. Reports state,
              not progress — it is asked never to give a percentage as an answer.
            </p>
          </div>
          <Button size="sm" variant="outline" disabled={loading} onClick={run}>
            {loading ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Sparkles className="size-3.5" />
            )}
            {result ? "Refresh" : "Brief me"}
          </Button>
        </div>

        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
            <p>{error}</p>
          </div>
        )}

        {result && (
          <div className="space-y-3 border-t pt-4">
            <p className="text-sm font-medium">{result.headline}</p>

            {result.items.length > 0 && (
              <div className="space-y-2">
                {result.items.map((item, i) => (
                  <div
                    key={`${item.programme}-${i}`}
                    className="flex items-start justify-between gap-3 rounded-lg border px-3 py-2 text-xs"
                  >
                    <div className="min-w-0">
                      <p className="font-medium">{item.programme}</p>
                      <p className="mt-0.5 text-muted-foreground">{item.state}</p>
                    </div>
                    {item.needs_a_decision && (
                      <Badge variant="warning">Needs a decision</Badge>
                    )}
                  </div>
                ))}
              </div>
            )}

            <p className="text-xs text-muted-foreground">
              Advisory. Each programme&rsquo;s own readiness below is the record.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
