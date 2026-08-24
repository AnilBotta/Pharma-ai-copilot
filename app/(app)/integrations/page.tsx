"use client";

import * as React from "react";
import { AlertTriangle, CheckCircle2, Circle, Plug, XCircle } from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type Health } from "@/lib/api";

const DESCRIPTIONS: Record<string, string> = {
  openai: "Model provider. Required: no agent can run without it.",
  pubmed: "NCBI E-utilities. Works without a key at a lower rate limit.",
  europepmc: "Europe PMC. Requires no credentials.",
  epo_ops: "EPO Open Patent Services. Required for patent retrieval.",
  crossref: "DOI metadata enrichment. Optional.",
  openalex: "Broader discovery and citation relationships. Optional.",
  uspto: "Optional secondary patent source.",
};

const SETUP_LINKS: Record<string, { label: string; href: string }> = {
  openai: { label: "platform.openai.com", href: "https://platform.openai.com/api-keys" },
  pubmed: { label: "NCBI account settings", href: "https://account.ncbi.nlm.nih.gov/" },
  epo_ops: { label: "developers.epo.org", href: "https://developers.epo.org/" },
};

export default function IntegrationsPage() {
  const [health, setHealth] = React.useState<Health | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let active = true;
    api
      .health()
      .then((h) => active && setHealth(h))
      .catch(
        (err) =>
          active &&
          setError(
            err instanceof Error
              ? `${err.message} The backend may not be running.`
              : String(err)
          )
      )
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  const required = health?.integrations.filter((i) => i.required) ?? [];
  const optional = health?.integrations.filter((i) => !i.required) ?? [];

  return (
    <div className="space-y-8">
      <PageHeader
        title="Integrations"
        description="Which external data sources are configured. Unconfigured providers degrade a run honestly rather than failing it."
        icon={Plug}
      />

      {error && (
        <Card variant="flush" tone="danger">
          <CardContent className="flex items-start gap-3 py-4">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-danger" />
            <p className="text-sm text-danger">{error}</p>
          </CardContent>
        </Card>
      )}

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-xl" />
          ))}
        </div>
      ) : (
        health && (
          <>
            <Card>
              <CardHeader>
                <CardTitle className="text-md">Backend</CardTitle>
              </CardHeader>
              <CardContent className="flex items-center gap-3">
                {health.status === "ok" ? (
                  <CheckCircle2 className="size-5 text-success" />
                ) : (
                  <AlertTriangle className="size-5 text-warning" />
                )}
                <div>
                  <p className="text-sm font-medium">
                    API {health.status === "ok" ? "healthy" : "degraded"}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Database: {health.database}
                  </p>
                </div>
              </CardContent>
            </Card>

            <section className="space-y-3">
              <h2 className="text-sm font-semibold">Required</h2>
              {required.map((integration) => (
                <IntegrationRow key={integration.name} integration={integration} />
              ))}
            </section>

            <section className="space-y-3">
              <h2 className="text-sm font-semibold">Optional</h2>
              {optional.map((integration) => (
                <IntegrationRow key={integration.name} integration={integration} />
              ))}
            </section>

            <p className="text-xs leading-relaxed text-muted-foreground">
              Credentials are configured server-side in{" "}
              <code className="rounded bg-muted px-1 py-0.5">backend/.env</code> and
              are never sent to the browser. This page reports only whether each
              provider is configured; it never displays a key.
            </p>
          </>
        )
      )}
    </div>
  );
}

function IntegrationRow({
  integration,
}: {
  integration: Health["integrations"][number];
}) {
  const link = SETUP_LINKS[integration.name];

  return (
    <Card>
      <CardContent className="flex items-start gap-3 py-4">
        <StateIcon state={integration.state} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium capitalize">
              {integration.name.replace(/_/g, " ")}
            </p>
            <StateBadge state={integration.state} />
            {integration.required && <Badge variant="outline">required</Badge>}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {DESCRIPTIONS[integration.name] ?? integration.detail}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">{integration.detail}</p>
          {integration.state === "not_configured" && link && (
            <a
              href={link.href}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 inline-block text-xs text-primary hover:underline"
            >
              Get credentials at {link.label}
            </a>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function StateIcon({ state }: { state: string }) {
  if (state === "configured")
    return <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-success" />;
  if (state === "keyless")
    return <Circle className="mt-0.5 size-5 shrink-0 text-info" />;
  return <XCircle className="mt-0.5 size-5 shrink-0 text-muted-foreground" />;
}

function StateBadge({ state }: { state: string }) {
  if (state === "configured") return <Badge variant="success">Configured</Badge>;
  if (state === "keyless") return <Badge variant="info">No key needed</Badge>;
  return <Badge variant="muted">Not configured</Badge>;
}
