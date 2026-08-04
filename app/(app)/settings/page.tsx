"use client";

import * as React from "react";
import { useTheme } from "next-themes";
import { motion } from "framer-motion";
import {
  Bell,
  Building2,
  Check,
  Eye,
  EyeOff,
  KeyRound,
  Laptop,
  Moon,
  Palette,
  Save,
  Settings2,
  Sun,
  UserRound,
  Zap,
} from "lucide-react";

import { useAuth } from "@/components/auth-provider";
import { PageHeader } from "@/components/shared/page-header";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { cn, maskApiKey } from "@/lib/utils";

const models = [
  { id: "gpt-4.1", name: "GPT-4.1", desc: "Best balance · research grade", color: "bg-blue-600" },
  { id: "gpt-4.1-mini", name: "GPT-4.1 mini", desc: "Fast & economical", color: "bg-sky-500" },
  { id: "o4-mini", name: "o4-mini", desc: "Reasoning for complex R&D", color: "bg-violet-600" },
  { id: "claude-4.5", name: "Claude 4.5", desc: "Long-form document analysis", color: "bg-amber-600" },
];

const notificationToggles = [
  { key: "Patent alerts", detail: "New filings, expiries and infringement flags", initial: true },
  { key: "Agent completions", detail: "When an agent finishes a long-running analysis", initial: true },
  { key: "Weekly digest", detail: "Monday summary of activity across the workspace", initial: false },
  { key: "Report ready", detail: "Notify when board-ready reports finish exporting", initial: true },
];

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

function FieldRow({
  label,
  hint,
  control,
}: {
  label: string;
  hint?: string;
  control: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <p className="text-sm font-medium">{label}</p>
        {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
      </div>
      {control}
    </div>
  );
}

export default function SettingsPage() {
  const { user, org } = useAuth();
  const { resolvedTheme, setTheme } = useTheme();
  const [activeTab, setActiveTab] = React.useState("profile");
  const [saved, setSaved] = React.useState(false);
  const [showKey, setShowKey] = React.useState(false);
  const [apiKey, setApiKey] = React.useState("sk-proj-aB3x9KqP2wLm7RtY4zVc8NfQ1sXpD5gJ");
  const [model, setModel] = React.useState(models[0].id);

  function flashSaved() {
    setSaved(true);
    setTimeout(() => setSaved(false), 1800);
  }

  const tabs = [
    { id: "profile", label: "Profile", icon: UserRound },
    { id: "organization", label: "Organization", icon: Building2 },
    { id: "ai", label: "AI & API", icon: Zap },
    { id: "appearance", label: "Appearance", icon: Palette },
    { id: "notifications", label: "Notifications", icon: Bell },
  ];

  return (
    <div className="space-y-8">
      <PageHeader
        title="Settings"
        description="Manage your profile, organization, AI providers and workspace preferences."
        icon={Settings2}
        actions={
          <Button onClick={flashSaved} className="gap-2">
            {saved ? <Check className="size-4" /> : <Save className="size-4" />}
            {saved ? "Saved" : "Save changes"}
          </Button>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
        {/* Tab rail */}
        <motion.nav
          initial={{ opacity: 0, x: -10 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.4 }}
          className="no-print flex gap-1.5 overflow-x-auto lg:flex-col lg:gap-1"
        >
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              className={cn(
                "flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium transition-all",
                activeTab === t.id
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground"
              )}
            >
              <t.icon className="size-4" />
              {t.label}
            </button>
          ))}
        </motion.nav>

        {/* Panels */}
        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
        >
          {activeTab === "profile" && (
            <Card>
              <CardHeader>
                <CardTitle className="text-[15px]">Personal profile</CardTitle>
                <CardDescription>Shown across the workspace and in generated reports.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="flex items-center gap-4">
                  <Avatar className="size-16">
                    <AvatarFallback className={cn(user.avatarColor, "text-lg text-white")}>
                      {user.initials}
                    </AvatarFallback>
                  </Avatar>
                  <div>
                    <Button variant="outline" size="sm">Change avatar</Button>
                    <p className="mt-1 text-[11px] text-muted-foreground">JPG or PNG, max 2 MB</p>
                  </div>
                </div>
                <div className="grid gap-5 sm:grid-cols-2">
                  <Field label="Full name">
                    <Input defaultValue={user.name} />
                  </Field>
                  <Field label="Title">
                    <Input defaultValue={user.title} />
                  </Field>
                  <Field label="Work email">
                    <Input type="email" defaultValue={user.email} />
                  </Field>
                  <Field label="Department">
                    <Input defaultValue={user.department} />
                  </Field>
                </div>
                <div className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    <span className="font-medium text-amber-700 dark:text-amber-400">Note:</span>{" "}
                    GxP environments require SSO + two-factor authentication. Contact your IT admin.
                  </p>
                </div>
              </CardContent>
            </Card>
          )}

          {activeTab === "organization" && (
            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle className="text-[15px]">Organization</CardTitle>
                  <CardDescription>Workspace identity used on every exported report.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-5">
                  <div className="grid gap-5 sm:grid-cols-2">
                    <Field label="Organization name">
                      <Input defaultValue={org.name} />
                    </Field>
                    <Field label="Industry">
                      <Input defaultValue={org.industry} />
                    </Field>
                    <Field label="Company size">
                      <Select defaultValue={org.size}>
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="1-50">1–50 employees</SelectItem>
                          <SelectItem value="51-200">51–200 employees</SelectItem>
                          <SelectItem value="501-1000">501–1000 employees</SelectItem>
                          <SelectItem value="1000+">1000+ employees</SelectItem>
                        </SelectContent>
                      </Select>
                    </Field>
                    <Field label="HQ country">
                      <Input defaultValue={org.country} />
                    </Field>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-[15px]">Subscription & usage</CardTitle>
                </CardHeader>
                <CardContent className="space-y-5">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium">{org.subscription} plan</p>
                      <p className="text-xs text-muted-foreground">Annual · renews Dec 2026</p>
                    </div>
                    <Badge variant="info">Active</Badge>
                  </div>
                  <div className="space-y-4">
                    <div>
                      <div className="mb-1.5 flex items-center justify-between text-xs">
                        <span className="text-muted-foreground">Agent seats</span>
                        <span className="font-medium">{org.seats} of 100</span>
                      </div>
                      <Progress value={org.seats} className="h-2" />
                    </div>
                    <div>
                      <div className="mb-1.5 flex items-center justify-between text-xs">
                        <span className="text-muted-foreground">Document storage</span>
                        <span className="font-medium">
                          {org.storageUsed} / {org.storageTotal} GB
                        </span>
                      </div>
                      <Progress value={(org.storageUsed / org.storageTotal) * 100} className="h-2" />
                    </div>
                  </div>
                  <Button variant="outline" size="sm">Manage billing</Button>
                </CardContent>
              </Card>
            </div>
          )}

          {activeTab === "ai" && (
            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-[15px]">
                    <KeyRound className="size-4 text-blue-600 dark:text-blue-400" />
                    OpenAI API key
                  </CardTitle>
                  <CardDescription>
                    Used by all agents for grounded research. Stored encrypted at rest; never logged.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <Field label="API key">
                    <div className="relative">
                      <Input
                        type={showKey ? "text" : "password"}
                        value={showKey ? apiKey : maskApiKey(apiKey)}
                        onChange={(e) => setApiKey(e.target.value)}
                        className="pr-10 font-mono text-xs"
                      />
                      <button
                        type="button"
                        onClick={() => setShowKey((v) => !v)}
                        className="absolute top-1/2 right-3 -translate-y-1/2 text-muted-foreground transition-colors hover:text-foreground"
                        aria-label={showKey ? "Hide key" : "Show key"}
                      >
                        {showKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                      </button>
                    </div>
                  </Field>
                  <div className="flex items-center gap-2">
                    <Badge variant="success">Connected</Badge>
                    <p className="text-xs text-muted-foreground">Last verified 4 minutes ago</p>
                  </div>
                  <Button variant="outline" size="sm">Regenerate key</Button>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-[15px]">Default model</CardTitle>
                  <CardDescription>Used by agents when no model is specified per task.</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2.5">
                    {models.map((m) => (
                      <button
                        key={m.id}
                        onClick={() => setModel(m.id)}
                        className={cn(
                          "flex w-full items-center gap-3 rounded-xl border p-3.5 text-left transition-all",
                          model === m.id
                            ? "border-blue-500/50 bg-blue-500/5 ring-2 ring-blue-500/20"
                            : "hover:border-border hover:bg-accent/50"
                        )}
                      >
                        <span className={cn("flex size-8 items-center justify-center rounded-lg text-white", m.color)}>
                          <Zap className="size-4" />
                        </span>
                        <div className="flex-1">
                          <p className="text-sm font-medium">{m.name}</p>
                          <p className="text-xs text-muted-foreground">{m.desc}</p>
                        </div>
                        {model === m.id && <Check className="size-4 text-blue-600 dark:text-blue-400" />}
                      </button>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {activeTab === "appearance" && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-[15px]">
                  <Palette className="size-4 text-blue-600 dark:text-blue-400" />
                  Theme & appearance
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-5">
                <Field label="Theme">
                  <div className="grid grid-cols-3 gap-2">
                    {(
                      [
                        { id: "light", label: "Light", icon: Sun },
                        { id: "dark", label: "Dark", icon: Moon },
                        { id: "system", label: "System", icon: Laptop },
                      ] as const
                    ).map((t) => (
                      <button
                        key={t.id}
                        onClick={() => setTheme(t.id)}
                        className={cn(
                          "flex flex-col items-center gap-2 rounded-xl border p-4 transition-all",
                          resolvedTheme === t.id
                            ? "border-blue-500/50 bg-blue-500/5 ring-2 ring-blue-500/20"
                            : "hover:border-border hover:bg-accent/50"
                        )}
                      >
                        <t.icon className="size-5 text-muted-foreground" />
                        <span className="text-xs font-medium">{t.label}</span>
                      </button>
                    ))}
                  </div>
                </Field>
                <Field label="Interface accent">
                  <div className="flex items-center gap-2.5">
                    {[
                      { c: "oklch(0.55 0.22 262)", active: true },
                      { c: "oklch(0.62 0.19 225)", active: false },
                      { c: "oklch(0.65 0.2 300)", active: false },
                      { c: "oklch(0.6 0.16 145)", active: false },
                      { c: "oklch(0.6 0.18 30)", active: false },
                    ].map((a, i) => (
                      <button
                        key={a.c}
                        className={cn(
                          "size-8 rounded-full border-2 border-background transition-transform hover:scale-110",
                          a.active && "ring-2 ring-blue-500/40 ring-offset-2 ring-offset-background"
                        )}
                        style={{ background: a.c }}
                        aria-label={`Accent ${i + 1}`}
                      />
                    ))}
                  </div>
                </Field>
                <div className="h-px bg-border" />
                <FieldRow label="Reduce motion" hint="Minimize animations across the workspace" control={<Switch defaultChecked={false} />} />
              </CardContent>
            </Card>
          )}

          {activeTab === "notifications" && (
            <Card>
              <CardHeader>
                <CardTitle className="text-[15px]">Notifications</CardTitle>
                <CardDescription>Choose how the platform keeps you informed.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {notificationToggles.map((n) => (
                  <div key={n.key} className="flex items-center justify-between gap-4 rounded-xl border p-4">
                    <div className="flex-1">
                      <p className="text-sm font-medium">{n.key}</p>
                      <p className="mt-0.5 text-xs text-muted-foreground">{n.detail}</p>
                    </div>
                    <Switch defaultChecked={n.initial} />
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </motion.div>
      </div>
    </div>
  );
}