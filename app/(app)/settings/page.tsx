"use client";

// Required, and not obvious: this page renders no state and looks like a
// server component, but PageHeader and Card are built on Framer Motion, which
// is client-only. Without this the route type-checks, lints, and then fails at
// prerender with "Attempted to call createMotionComponent() from the server" -
// which breaks the production build rather than the page.

import Link from "next/link";
import {
  BellRing,
  ChevronRight,
  FileCheck2,
  Plug,
  Settings as SettingsIcon,
} from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { Card, CardContent } from "@/components/ui/card";

/**
 * The settings index.
 *
 * The sidebar has carried a "Settings" link to this path since before any
 * settings existed, and it returned a bare Next.js 404 — a dead link in the
 * permanent furniture of the application, which is worse than no link at all.
 *
 * A redirect to Notifications would fix the 404 and mislead: Integrations is
 * configuration too, so landing on one of them under a heading that promises
 * both would leave the other unfindable from here.
 */

const AREAS = [
  {
    href: "/settings/notifications",
    label: "Notifications",
    icon: BellRing,
    description:
      "Who receives stage-gate alerts, which ones they get, and whether they arrive immediately or as a daily summary.",
  },
  {
    href: "/integrations",
    label: "Integrations",
    icon: Plug,
    description:
      "Which external providers are configured, and what stops working when one is not.",
  },
  {
    href: "/settings/sas-validation",
    label: "SAS Validation",
    icon: FileCheck2,
    description:
      "An optional independent check of results the engine already computed. Nothing here is required to use any supported calculation.",
  },
];

export default function SettingsPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Settings"
        description="Configuration for this workspace."
        icon={SettingsIcon}
      />

      <div className="space-y-3">
        {AREAS.map((area) => (
          <Link key={area.href} href={area.href} className="block">
            <Card className="transition-colors hover:bg-accent/50">
              <CardContent className="flex items-center gap-4 py-4">
                <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-muted text-muted-foreground">
                  <area.icon className="size-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{area.label}</p>
                  <p className="mt-0.5 text-sm text-muted-foreground">
                    {area.description}
                  </p>
                </div>
                <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
