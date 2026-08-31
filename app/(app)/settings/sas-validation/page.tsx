"use client";

// Client component for the same reason the settings index is one: PageHeader
// and Card are built on Framer Motion, which is client-only, and a server
// render fails at prerender rather than at type-check.

import Link from "next/link";
import {
  ArrowLeft,
  CheckCircle2,
  Download,
  FileCheck2,
  Lock,
  ServerCog,
  Upload,
} from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * SAS Validation.
 *
 * The first question is "how would you like to use SAS?", not "paste your
 * credentials". Two of the three answers are not available yet, and this page
 * says so in the option itself rather than hiding them: a customer evaluating
 * the product should be able to see that a managed service is intended, and a
 * customer who needs one today should be able to tell that it is not here.
 *
 * The alternative - showing only what works - reads as though manual upload
 * were the whole plan, and the alternative to THAT - showing all three as
 * though they worked - is worse, because the first person to click Connect
 * finds out by failing.
 *
 * No credential field appears anywhere on this page. Manual validation needs
 * none, and the two modes that would are not available to configure.
 */

type Availability = "available" | "not-yet";

const OPTIONS: {
  mode: string;
  title: string;
  blurb: string;
  detail: string;
  availability: Availability;
  icon: typeof ServerCog;
  notice: string;
}[] = [
  {
    mode: "managed",
    title: "Managed SAS",
    blurb: "Use our managed SAS validation service.",
    detail:
      "We run the validation for you against a SAS environment we operate. Nothing to install and no SAS licence of your own required.",
    availability: "not-yet",
    icon: ServerCog,
    notice:
      "Managed SAS availability depends on your subscription and our licensed service availability.",
  },
  {
    mode: "customer_viya",
    title: "Connect my SAS",
    blurb: "Use your organisation's SAS environment.",
    detail:
      "We submit the validation to a SAS environment your organisation already licenses and operates.",
    availability: "not-yet",
    icon: Lock,
    notice: "Your SAS environment remains under your organisation's control.",
  },
  {
    mode: "manual_upload",
    title: "Manual validation",
    blurb: "Generate a SAS package, run it internally, and upload the results.",
    detail:
      "We generate a dataset, a SAS program and a manifest. You run it inside your own environment and upload what SAS produced. No credential is stored and nothing connects outward.",
    availability: "available",
    icon: FileCheck2,
    notice: "Your SAS environment remains under your organisation's control.",
  },
];

const MANUAL_STEPS = [
  {
    icon: Download,
    title: "Generate and download the package",
    body: "A dataset, the exact SAS program, a model specification and a manifest of SHA-256 hashes. The package is immutable: change anything and you get a new one rather than an edited one.",
  },
  {
    icon: ServerCog,
    title: "Run it in your own SAS",
    body: "Set the package folder in validate.sas and run it. The PROC MIXED statements are reproduced verbatim from the regulatory source, so please do not edit them.",
  },
  {
    icon: Upload,
    title: "Upload the result and the log",
    body: "We check the hashes against the package, parse the structured result file, and keep the original upload as evidence.",
  },
  {
    icon: CheckCircle2,
    title: "A reviewer reads the comparison",
    body: "The SAS numbers are shown beside our engine's and beside the published reference values. An upload never changes a method's validation status on its own.",
  },
];

export default function SasValidationSettingsPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="SAS Validation"
        description="An optional independent check of results the engine already computed."
        icon={FileCheck2}
      />

      <Link
        href="/settings"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" />
        Settings
      </Link>

      {/* Said plainly and first. A customer with no SAS should not have to
          work out from the absence of a warning that they are fine. */}
      <Card className="border-dashed">
        <CardContent className="py-4 text-sm text-muted-foreground">
          SAS validation is optional. Every bioequivalence result this
          application produces is calculated by its own engine, and nothing on
          this page is required to use any supported calculation.
        </CardContent>
      </Card>

      <section className="space-y-3">
        <h2 className="text-sm font-medium">How would you like to use SAS?</h2>

        {OPTIONS.map((option) => {
          const available = option.availability === "available";
          return (
            <Card
              key={option.mode}
              className={available ? "" : "opacity-75"}
              aria-disabled={!available}
            >
              <CardHeader className="flex flex-row items-start gap-4 space-y-0 pb-3">
                <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-muted text-muted-foreground">
                  <option.icon className="size-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <CardTitle className="text-sm">{option.title}</CardTitle>
                    {available ? (
                      <Badge variant="secondary">Available</Badge>
                    ) : (
                      <Badge variant="outline">Not yet available</Badge>
                    )}
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {option.blurb}
                  </p>
                </div>
              </CardHeader>
              <CardContent className="space-y-2 pl-[3.5rem] text-sm text-muted-foreground">
                <p>{option.detail}</p>
                <p className="text-xs">{option.notice}</p>
                {!available && (
                  <p className="text-xs">
                    Not available in this release. Manual validation is
                    available now and keeps your SAS environment entirely under
                    your organisation&apos;s control.
                  </p>
                )}
              </CardContent>
            </Card>
          );
        })}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium">How manual validation works</h2>
        <Card>
          <CardContent className="divide-y py-0">
            {MANUAL_STEPS.map((step, index) => (
              <div key={step.title} className="flex gap-4 py-4">
                <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-xs font-medium text-muted-foreground">
                  {index + 1}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{step.title}</p>
                  <p className="mt-0.5 text-sm text-muted-foreground">
                    {step.body}
                  </p>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      </section>

      {/* The single most important sentence on the page, so it is not buried
          in the step list where it would be read as a process note. */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">What a SAS result does and does not do</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>
            An uploaded SAS output is recorded as external validation evidence
            and compared with the engine&apos;s own result. It is not treated as
            the correct answer, and it does not change any method&apos;s
            validation status.
          </p>
          <p>
            Changing what a method is qualified for is a separate, governed
            statistical change, made only after a named reviewer has recorded a
            decision on the comparison.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
