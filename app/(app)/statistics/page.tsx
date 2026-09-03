"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  BadgeCheck,
  CircleSlash,
  FlaskConical,
  Loader2,
  RefreshCw,
  ShieldQuestion,
} from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  statistics,
  type DossierSummary,
  type MethodCatalogueEntry,
  type StatisticalDisplayStatus,
} from "@/lib/api";

/**
 * Statistical methods.
 *
 * WHAT THIS PAGE IS FOR, AND THE ONE THING IT MUST NOT DO
 *
 * A customer deciding whether to run their study through this engine tomorrow.
 * The single failure to avoid is showing every method as "Available", because
 * "the code runs" and "a regulator's published output has been reproduced
 * through it" are different claims and only the second one supports a filing.
 *
 * So there are three states and never one:
 *
 *   VALIDATED                        rely on it
 *   IMPLEMENTED — VALIDATION PENDING it returns a number, unchecked against
 *                                    any regulator's published output
 *   NOT IMPLEMENTED                  it refuses, and says what would change
 *
 * The qualification under each row is not fine print. It is the sentence that
 * makes the badge mean something, so it sits at full size beside the status
 * rather than in a tooltip somebody has to go looking for.
 *
 * WHY THE OPEN QUESTIONS ARE ON THE PAGE
 *
 * A status page that lists only what works reads as a claim that nothing is
 * outstanding. The blockers and open findings are shown, in the customer's
 * terms, because a reader who cannot see why partial-replicate Appendix C
 * refuses cannot tell whether it will refuse for their study.
 */

const STATUS_STYLE: Record<
  StatisticalDisplayStatus,
  { variant: BadgeVariant; icon: typeof BadgeCheck; blurb: string }
> = {
  VALIDATED: {
    variant: "success",
    icon: BadgeCheck,
    blurb:
      "The regulator's own published numerical output has been reproduced through this path.",
  },
  "IMPLEMENTED - VALIDATION PENDING": {
    variant: "warning",
    icon: ShieldQuestion,
    blurb:
      "The method runs and returns a result. No regulator-published output has been reproduced through it, so the result carries that qualification.",
  },
  "NOT IMPLEMENTED": {
    variant: "muted",
    icon: CircleSlash,
    blurb:
      "Studies routed here receive no verdict. The engine refuses and names the reason rather than returning a number.",
  },
};

/** Shown once, above the table, so the badges are read correctly. */
const LEGEND: StatisticalDisplayStatus[] = [
  "VALIDATED",
  "IMPLEMENTED - VALIDATION PENDING",
  "NOT IMPLEMENTED",
];

function StatusBadge({ status }: { status: StatisticalDisplayStatus }) {
  const style = STATUS_STYLE[status] ?? STATUS_STYLE["NOT IMPLEMENTED"];
  const Icon = style.icon;
  return (
    <Badge variant={style.variant} className="whitespace-nowrap">
      <Icon className="size-3" />
      {status}
    </Badge>
  );
}

function MethodCard({ entry }: { entry: MethodCatalogueEntry }) {
  return (
    <Card>
      <CardHeader className="gap-2 pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="text-sm">{entry.method}</CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              {entry.jurisdiction} · {entry.design} · {entry.supported_endpoints}
            </p>
          </div>
          <StatusBadge status={entry.status} />
        </div>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <p>{entry.qualification}</p>
        {entry.key_limitation && (
          <p className="text-muted-foreground">{entry.key_limitation}</p>
        )}
        <p className="text-xs text-muted-foreground">{entry.regulatory_source}</p>
      </CardContent>
    </Card>
  );
}

export default function StatisticsPage() {
  const [dossier, setDossier] = useState<DossierSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setDossier(await statistics.dossier());
    } catch (caught) {
      // Reported, never swallowed. A status page that fails silently shows an
      // empty method list, which reads as "this engine does nothing".
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Statistical Methods"
        description="What the bioequivalence engine can do, and how far each method has been checked."
        icon={FlaskConical}
      />

      <Card className="border-dashed">
        <CardContent className="space-y-3 py-4 text-sm">
          <p className="text-muted-foreground">
            Two questions are answered separately here, because they have
            different answers. <strong>Implemented</strong> means the method
            runs. <strong>Validated</strong> means a regulator&apos;s own
            published numerical output has been reproduced through it. Only the
            second supports a submission.
          </p>
          <div className="grid gap-2 sm:grid-cols-3">
            {LEGEND.map((status) => (
              <div key={status} className="space-y-1">
                <StatusBadge status={status} />
                <p className="text-xs text-muted-foreground">
                  {STATUS_STYLE[status].blurb}
                </p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {loading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Loading the method catalogue…
        </div>
      )}

      {error && (
        <Card className="border-danger-border">
          <CardContent className="space-y-3 py-4 text-sm">
            <p className="font-medium">The method catalogue could not be loaded.</p>
            <p className="text-muted-foreground">{error}</p>
            <p className="text-xs text-muted-foreground">
              Nothing about your studies has changed. This page reports what the
              engine supports; it takes no part in any calculation.
            </p>
            <Button variant="outline" size="sm" onClick={() => void load()}>
              <RefreshCw className="size-3.5" />
              Retry
            </Button>
          </CardContent>
        </Card>
      )}

      {dossier && (
        <>
          <section className="space-y-3">
            <h2 className="text-sm font-medium">Methods</h2>
            <div className="grid gap-3">
              {dossier.catalogue.map((entry) => (
                <MethodCard key={entry.capability_id} entry={entry} />
              ))}
            </div>
          </section>

          {dossier.blockers.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-sm font-medium">What is outstanding</h2>
              <p className="text-sm text-muted-foreground">
                Listed because a page showing only what works reads as a claim
                that nothing is outstanding.
              </p>
              {dossier.blockers.map((blocker) => (
                <Card key={blocker.blocker_id}>
                  <CardHeader className="flex flex-row items-start gap-3 space-y-0 pb-2">
                    <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
                    <CardTitle className="text-sm">{blocker.summary}</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 pl-[2.75rem] text-sm text-muted-foreground">
                    {blocker.current_behaviour && (
                      <p>{blocker.current_behaviour}</p>
                    )}
                    <p className="text-xs">
                      <span className="font-medium text-foreground">
                        Resolved by:{" "}
                      </span>
                      {blocker.required_evidence}
                    </p>
                  </CardContent>
                </Card>
              ))}
            </section>
          )}

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">
                How a method&apos;s status changes
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-muted-foreground">
              <p>
                A method is promoted only when a regulator&apos;s published
                numerical output has been reproduced, the regulatory source is
                pinned to a document version, no blocking question is open
                against it, and a named reviewer has recorded the decision. One
                numerical match is not enough on its own.
              </p>
              {/* Stated per kind, not as one figure. An earlier version of
                  this paragraph said every constant carried a document,
                  section and version — which was not true of the two
                  conventional-interval limits, nor of values this package
                  computes rather than cites. One combined number invited
                  exactly that overstatement. */}
              <p>
                Engine version {dossier.be_stats_version}. It uses{" "}
                {dossier.provenance.normative} regulatory constants written by
                a regulator, {dossier.provenance.normative_pinned} of which are
                pinned to a named document, section and version; the remaining{" "}
                {dossier.provenance.normative_exceptions} carry a recorded
                reason and are tracked as open work. A further{" "}
                {dossier.provenance.derived} values are computed from those,
                and every one states its formula and its inputs rather than
                being cited to a regulator that never stated it.
              </p>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
