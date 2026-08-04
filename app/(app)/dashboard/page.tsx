"use client";

import { LayoutDashboard } from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { Card, CardContent } from "@/components/ui/card";

/**
 * Placeholder. The real dashboard is built in stage 7 against live data from
 * `research_runs` and `usage_records`.
 *
 * The previous version of this page rendered fabricated pipeline charts and
 * activity feeds from `lib/data.ts`. Those fixtures have been deleted. Nothing
 * is shown here until there are real runs to show.
 */
export default function DashboardPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Dashboard"
        description="Research activity across your projects."
        icon={LayoutDashboard}
      />
      <Card>
        <CardContent className="py-12 text-center">
          <p className="text-sm font-medium">Backend under construction</p>
          <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
            The demo fixtures that previously populated this page have been
            removed. Live metrics appear here once the research backend is
            connected.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
