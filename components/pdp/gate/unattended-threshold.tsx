"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { GateWorkspace } from "@/lib/api";
/**
 * How long this gate may sit untouched before an alert is raised.
 *
 * Shows whether the number was chosen here or inherited, because printing only
 * the effective value would make a system default look like somebody's
 * decision — and the point of an inactivity alert is that it reflects a
 * deliberate expectation about this gate's tempo.
 */
export function UnattendedThreshold({
  stage,
  busy,
  onSet,
}: {
  stage: GateWorkspace["stage"];
  busy: boolean;
  onSet: (days: number | null) => void;
}) {
  const effective = stage.unattended_effective_days ?? 7;
  const inherited = stage.unattended_is_inherited ?? true;
  const [value, setValue] = React.useState(String(effective));

  React.useEffect(() => {
    setValue(String(effective));
  }, [effective]);

  const parsed = Number.parseInt(value, 10);
  const valid = Number.isFinite(parsed) && parsed >= 1 && parsed <= 365;
  const changed = valid && parsed !== effective;

  return (
    <Card variant="flush">
      <CardContent className="flex flex-wrap items-end gap-4 py-4">
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <p className="type-label text-muted-foreground">
              Report this gate as unattended after
            </p>
            {/* The provenance is the point — an inherited default is not
                somebody's expectation about this gate's tempo, and it used to
                be stated only in a sentence below the control. */}
            <Badge variant={inherited ? "muted" : "info"}>
              {inherited ? "System default" : "Set for this gate"}
            </Badge>
          </div>
          <p className="max-w-prose text-sm text-muted-foreground">
            Days with no recorded activity — no evidence attached, no approval,
            no status change — before an alert is raised for the gate as a whole.
          </p>
        </div>

        <div className="flex items-end gap-2">
          <div className="space-y-1">
            <Label htmlFor="unattended-days" className="text-xs">
              Days
            </Label>
            <Input
              id="unattended-days"
              type="number"
              min={1}
              max={365}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="w-24"
            />
          </div>
          <Button
            size="sm"
            disabled={busy || !changed}
            onClick={() => onSet(parsed)}
          >
            Save
          </Button>
          {!inherited && (
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => onSet(null)}
            >
              Use default
            </Button>
          )}
        </div>

        <p className="w-full text-2xs text-muted-foreground">
          {inherited
            ? `Currently ${effective} days, inherited from the system default. Changing it here affects this gate only.`
            : `Set to ${effective} days for this gate specifically.`}
        </p>
      </CardContent>
    </Card>
  );
}
