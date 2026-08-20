"use client";

import * as React from "react";
import {
  AlertTriangle,
  BellRing,
  CheckCircle2,
  Mail,
  Plus,
  Trash2,
} from "lucide-react";

import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ApiError,
  notificationSettings,
  type AlertType,
  type NotificationRecipient,
} from "@/lib/api";
import { formatRelative } from "@/lib/utils";

/**
 * Who receives stage-gate alerts.
 *
 * Two things this page has to be honest about:
 *
 *   - An address here is a delivery address and nothing more. It grants no
 *     login and no authority, and it is emphatically not a way to give somebody
 *     approval rights. The page says so, because a settings screen that quietly
 *     conferred power would be the worst thing in this module.
 *
 *   - "Configured" is not "receiving". Each row shows how many alerts have
 *     actually reached it and when the last one did, so an address that was
 *     typed in wrongly is visible as one that has never been sent anything.
 */
export default function NotificationSettingsPage() {
  const [recipients, setRecipients] = React.useState<NotificationRecipient[]>([]);
  const [alertTypes, setAlertTypes] = React.useState<AlertType[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const [email, setEmail] = React.useState("");
  const [name, setName] = React.useState("");
  const [chosen, setChosen] = React.useState<string[]>([]);
  const [wantsImmediate, setWantsImmediate] = React.useState(true);
  const [wantsDigest, setWantsDigest] = React.useState(true);

  React.useEffect(() => {
    let active = true;
    Promise.all([notificationSettings.list(), notificationSettings.alertTypes()])
      .then(([list, types]) => {
        if (!active) return;
        setRecipients(list);
        setAlertTypes(types);
      })
      .catch((err) => active && setError(describe(err)))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  async function handleAdd() {
    if (!email.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const added = await notificationSettings.add({
        email: email.trim(),
        name: name.trim() || null,
        conditions: chosen,
        wants_immediate: wantsImmediate,
        wants_digest: wantsDigest,
      });
      setRecipients((prev) => [
        added,
        ...prev.filter((r) => r.id !== added.id),
      ]);
      setEmail("");
      setName("");
      setChosen([]);
    } catch (err) {
      setError(describe(err));
    } finally {
      setBusy(false);
    }
  }

  async function patch(
    id: string,
    body: Parameters<typeof notificationSettings.update>[1]
  ) {
    setError(null);
    try {
      const updated = await notificationSettings.update(id, body);
      setRecipients((prev) => prev.map((r) => (r.id === id ? updated : r)));
    } catch (err) {
      setError(describe(err));
    }
  }

  const active = recipients.filter((r) => r.is_active);
  const inactive = recipients.filter((r) => !r.is_active);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Notification recipients"
        description="Who receives stage-gate alerts, and which ones."
        icon={BellRing}
      />

      {error && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="flex items-start gap-3 py-4">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" />
            <p className="text-sm text-destructive">{error}</p>
          </CardContent>
        </Card>
      )}

      <Card className="border-sky-500/30 bg-sky-500/5">
        <CardContent className="py-4 text-sm text-muted-foreground">
          An address here receives email and nothing else. It creates no account,
          grants no permission, and does not allow anyone to approve a
          requirement or decide a gate — those come from roles, which are
          assigned separately and on purpose.
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-4 py-6">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="recipient-email">Email address</Label>
              <Input
                id="recipient-email"
                type="email"
                placeholder="name@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="recipient-name">Name (optional)</Label>
              <Input
                id="recipient-name"
                placeholder="Who this is"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
          </div>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Which alerts</legend>
            <p className="text-xs text-muted-foreground">
              Choose nothing to receive all of them.
            </p>
            <div className="flex flex-wrap gap-2 pt-1">
              {alertTypes.map((type) => {
                const on = chosen.includes(type.condition);
                return (
                  <button
                    key={type.condition}
                    type="button"
                    aria-pressed={on}
                    title={type.description ?? undefined}
                    onClick={() =>
                      setChosen((prev) =>
                        on
                          ? prev.filter((c) => c !== type.condition)
                          : [...prev, type.condition]
                      )
                    }
                    className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                      on
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-input hover:bg-muted"
                    }`}
                  >
                    {type.name}
                  </button>
                );
              })}
            </div>
          </fieldset>

          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={wantsImmediate}
                onChange={(e) => setWantsImmediate(e.target.checked)}
              />
              Email each alert as it happens
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={wantsDigest}
                onChange={(e) => setWantsDigest(e.target.checked)}
              />
              One daily summary of every open gate
            </label>
          </div>

          <Button onClick={handleAdd} disabled={busy || !email.trim()}>
            <Plus className="size-4" /> Add recipient
          </Button>
        </CardContent>
      </Card>

      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : active.length === 0 ? (
        <EmptyState
          icon={Mail}
          title="Nobody is being notified"
          description="Alerts are still raised and recorded, and are visible on the programme pages — but no email is going to anyone."
        />
      ) : (
        <div className="space-y-3">
          {active.map((r) => (
            <RecipientRow
              key={r.id}
              recipient={r}
              alertTypes={alertTypes}
              onPatch={patch}
            />
          ))}
        </div>
      )}

      {inactive.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-medium text-muted-foreground">
            Removed ({inactive.length})
          </h2>
          {inactive.map((r) => (
            <RecipientRow
              key={r.id}
              recipient={r}
              alertTypes={alertTypes}
              onPatch={patch}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function RecipientRow({
  recipient,
  alertTypes,
  onPatch,
}: {
  recipient: NotificationRecipient;
  alertTypes: AlertType[];
  onPatch: (
    id: string,
    body: Parameters<typeof notificationSettings.update>[1]
  ) => void;
}) {
  const names = new Map(alertTypes.map((t) => [t.condition, t.name]));
  const all = recipient.conditions.length === 0;

  return (
    <Card className={recipient.is_active ? "" : "opacity-60"}>
      <CardContent className="flex flex-wrap items-start gap-4 py-4">
        <Mail className="mt-0.5 size-5 shrink-0 text-muted-foreground" />

        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate text-sm font-medium">{recipient.email}</p>
            {recipient.name && (
              <span className="text-sm text-muted-foreground">
                {recipient.name}
              </span>
            )}
            {/* Configured is not the same as receiving. A typo looks exactly
                like a working address until you notice it has never been
                sent anything. */}
            {recipient.sent_count > 0 ? (
              <Badge variant="secondary" className="gap-1">
                <CheckCircle2 className="size-3" />
                {recipient.sent_count} sent
                {recipient.last_sent_at
                  ? `, last ${formatRelative(recipient.last_sent_at)}`
                  : ""}
              </Badge>
            ) : (
              <Badge variant="outline">Nothing sent yet</Badge>
            )}
          </div>

          <div className="flex flex-wrap gap-1.5">
            {all ? (
              <Badge variant="muted">All alert types</Badge>
            ) : (
              recipient.conditions.map((c) => (
                <Badge key={c} variant="muted">
                  {names.get(c) ?? c}
                </Badge>
              ))
            )}
          </div>

          <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={recipient.wants_immediate}
                onChange={(e) =>
                  onPatch(recipient.id, { wants_immediate: e.target.checked })
                }
              />
              Immediate
            </label>
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={recipient.wants_digest}
                onChange={(e) =>
                  onPatch(recipient.id, { wants_digest: e.target.checked })
                }
              />
              Daily summary
            </label>
          </div>
        </div>

        {recipient.is_active ? (
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Stop notifying ${recipient.email}`}
            onClick={() => onPatch(recipient.id, { is_active: false })}
          >
            <Trash2 className="size-4" />
          </Button>
        ) : (
          <Button
            variant="outline"
            size="sm"
            onClick={() => onPatch(recipient.id, { is_active: true })}
          >
            Restore
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function describe(err: unknown): string {
  return err instanceof ApiError ? err.message : String(err);
}
