"use client";

import * as React from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  ArrowRight,
  ArrowUpRight,
  FileText,
  FlaskConical,
  FileBarChart,
  MessageSquareText,
  Newspaper,
  Plus,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useAuth } from "@/components/auth-provider";
import { FadeUp, Stagger, StaggerItem } from "@/components/motion/primitives";
import { ChartCard } from "@/components/shared/chart-card";
import { ChartTooltip } from "@/components/shared/chart-tooltip";
import { PageHeader } from "@/components/shared/page-header";
import { StatusBadge } from "@/components/shared/status-badge";
import { StatCard } from "@/components/shared/stat-card";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { activity, patentActivity, pipelineByPhase, projects } from "@/lib/data";
import { AGENT_REGISTRY } from "@/lib/agents";
import { cn, formatRelative } from "@/lib/utils";

const agentQuickLinks = [
  { id: "agent-patent", href: "/patents", prompt: "Analyze the patent landscape for Semaglutide." },
  { id: "agent-literature", href: "/literature", prompt: "Review depot peptide delivery technologies." },
  { id: "agent-strategy", href: "/strategy", prompt: "Build a roadmap for an oral GLP-1 tablet." },
  { id: "agent-reports", href: "/reports", prompt: "Generate the quarterly IP dossier." },
];

const activityIcons: Record<string, React.ElementType> = {
  patent: ShieldCheck,
  literature: Newspaper,
  strategy: FlaskConical,
  report: FileBarChart,
  chat: MessageSquareText,
  project: Plus,
};

function DashboardSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-[118px] rounded-xl" />
        ))}
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        <Skeleton className="h-[300px] rounded-xl lg:col-span-2" />
        <Skeleton className="h-[300px] rounded-xl" />
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    const t = setTimeout(() => setLoading(false), 900);
    return () => clearTimeout(t);
  }, []);

  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";

  return (
    <div className="space-y-8">
      <PageHeader
        title={`${greeting}, ${user.name.split(" ")[1] ?? "researcher"}`}
        description="Here's what your AI agents found while you were away."
        icon={Sparkles}
        actions={
          <>
            <Button variant="outline" asChild>
              <Link href="/chat">
                <MessageSquareText className="size-4" /> New chat
              </Link>
            </Button>
            <Button asChild>
              <Link href="/reports">
                <Plus className="size-4" /> New report
              </Link>
            </Button>
          </>
        }
      />

      {loading ? (
        <DashboardSkeleton />
      ) : (
        <>
          {/* Stat cards */}
          <Stagger className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StaggerItem>
              <StatCard
                label="Active projects"
                value="5"
                delta="+2"
                deltaPositive
                hint="vs last quarter"
                icon={FlaskConical}
              />
            </StaggerItem>
            <StaggerItem>
              <StatCard
                label="Patent alerts"
                value="17"
                delta="+5"
                deltaPositive={false}
                hint="2 high severity"
                icon={ShieldCheck}
              />
            </StaggerItem>
            <StaggerItem>
              <StatCard
                label="Papers reviewed"
                value="1,284"
                delta="+12.4%"
                deltaPositive
                hint="this month"
                icon={Newspaper}
              />
            </StaggerItem>
            <StaggerItem>
              <StatCard
                label="Reports generated"
                value="46"
                delta="+8"
                deltaPositive
                hint="3 ready today"
                icon={FileText}
              />
            </StaggerItem>
          </Stagger>

          {/* Charts row */}
          <div className="grid gap-6 lg:grid-cols-3">
            <ChartCard
              title="Patent activity"
              description="Filings, grants and expiries · trailing 8 months"
              className="lg:col-span-2"
              action={
                <Link
                  href="/patents"
                  className="text-xs font-medium text-primary hover:underline"
                >
                  Open agent →
                </Link>
              }
            >
              <div className="h-[260px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={patentActivity} margin={{ top: 8, right: 4, left: -18, bottom: 0 }}>
                    <defs>
                      <linearGradient id="gradFilings" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="oklch(0.55 0.22 262)" stopOpacity={0.35} />
                        <stop offset="100%" stopColor="oklch(0.55 0.22 262)" stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="gradGrants" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="oklch(0.62 0.19 225)" stopOpacity={0.35} />
                        <stop offset="100%" stopColor="oklch(0.62 0.19 225)" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" opacity={0.6} />
                    <XAxis dataKey="month" tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} />
                    <Tooltip content={<ChartTooltip />} cursor={{ stroke: "var(--border)" }} />
                    <Area type="monotone" dataKey="filings" name="New filings" stroke="oklch(0.55 0.22 262)" strokeWidth={2} fill="url(#gradFilings)" />
                    <Area type="monotone" dataKey="grants" name="Grants" stroke="oklch(0.62 0.19 225)" strokeWidth={2} fill="url(#gradGrants)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </ChartCard>

            <ChartCard title="Pipeline mix" description="Active programs by phase">
              <div className="flex h-[260px] items-center gap-2">
                <div className="relative h-full flex-1">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={pipelineByPhase}
                        dataKey="value"
                        nameKey="phase"
                        innerRadius="62%"
                        outerRadius="92%"
                        paddingAngle={3}
                        strokeWidth={0}
                      >
                        {pipelineByPhase.map((entry) => (
                          <Cell key={entry.phase} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip content={<ChartTooltip />} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                    <p className="text-2xl font-semibold">{projects.filter((p) => p.status === "Active").length}</p>
                    <p className="text-[11px] text-muted-foreground">active programs</p>
                  </div>
                </div>
                <div className="w-32 space-y-2">
                  {pipelineByPhase.map((entry) => (
                    <div key={entry.phase} className="flex items-center gap-2 text-xs">
                      <span className="size-2.5 rounded-full" style={{ background: entry.color }} />
                      <span className="flex-1 truncate text-muted-foreground">{entry.phase}</span>
                      <span className="font-medium">{entry.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            </ChartCard>
          </div>

          {/* Quick actions */}
          <FadeUp>
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold tracking-tight">Quick actions</h2>
            </div>
            <div className="mt-3 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {agentQuickLinks.map((a) => {
                const agent = AGENT_REGISTRY.find((x) => x.id === a.id)!;
                const Icon = agent.icon;
                return (
                  <Link
                    key={a.id}
                    href={a.href}
                    className="group relative overflow-hidden rounded-xl border bg-card p-4 transition-all hover:-translate-y-0.5 hover:border-blue-500/40 hover:shadow-lg hover:shadow-blue-900/10"
                  >
                    <div className="pointer-events-none absolute -top-10 -right-10 size-28 rounded-full bg-gradient-to-br from-blue-500/10 to-violet-500/10 blur-xl transition-all duration-500 group-hover:from-blue-500/20 group-hover:to-violet-500/20" />
                    <div className="flex items-start justify-between">
                      <div className={cn("flex size-9 items-center justify-center rounded-lg border border-blue-500/20 bg-gradient-to-br from-blue-600/10 to-violet-600/10", agent.color)}>
                        <Icon className="size-[18px]" />
                      </div>
                      <ArrowUpRight className="size-4 text-muted-foreground opacity-0 transition-all group-hover:translate-x-0.5 group-hover:text-primary group-hover:opacity-100" />
                    </div>
                    <p className="mt-3 text-sm font-medium">{agent.name}</p>
                    <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">“{a.prompt}”</p>
                  </Link>
                );
              })}
            </div>
          </FadeUp>

          {/* Activity + projects */}
          <div className="grid gap-6 xl:grid-cols-3">
            <ChartCard title="Recent AI activity" description="What agents worked on today">
              <div className="space-y-1">
                {activity.map((item, i) => {
                  const Icon = activityIcons[item.icon] ?? Sparkles;
                  return (
                    <motion.div
                      key={item.id}
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.05, duration: 0.35 }}
                      className="group flex gap-3 rounded-lg px-2 py-2.5 transition-colors hover:bg-accent/60"
                    >
                      <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg border border-blue-500/15 bg-blue-500/8 text-blue-600 dark:text-blue-400">
                        <Icon className="size-3.5" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-[13px] leading-snug">
                          <span className="font-medium">{item.agent}</span>{" "}
                          <span className="text-muted-foreground">{item.action}</span>{" "}
                          <span className="font-medium text-foreground">{item.target}</span>
                        </p>
                        <div className="mt-0.5 flex items-center gap-2">
                          {item.meta && <Badge variant="info" className="px-1.5 py-0 text-[10px]">{item.meta}</Badge>}
                          <span className="text-[11px] text-muted-foreground">{formatRelative(item.time)}</span>
                        </div>
                      </div>
                    </motion.div>
                  );
                })}
              </div>
            </ChartCard>

            <ChartCard
              title="Recent projects"
              description="Latest development programs"
              className="xl:col-span-2"
              action={
                <Link href="/projects" className="text-xs font-medium text-primary hover:underline">
                  View all →
                </Link>
              }
            >
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Project</TableHead>
                    <TableHead className="hidden md:table-cell">Phase</TableHead>
                    <TableHead className="hidden lg:table-cell">Status</TableHead>
                    <TableHead className="w-[180px]">Progress</TableHead>
                    <TableHead className="hidden text-right sm:table-cell">Owner</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {projects.slice(0, 5).map((p, i) => (
                    <motion.tr
                      key={p.id}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.05, duration: 0.35 }}
                      className="group cursor-pointer"
                      onClick={() => (window.location.href = "/projects")}
                    >
                      <TableCell>
                        <div>
                          <p className="font-medium">{p.name}</p>
                          <p className="text-xs text-muted-foreground">
                            {p.code} · {p.molecule}
                          </p>
                        </div>
                      </TableCell>
                      <TableCell className="hidden md:table-cell">
                        <Badge variant="secondary">{p.phase}</Badge>
                      </TableCell>
                      <TableCell className="hidden lg:table-cell">
                        <StatusBadge status={p.status} />
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2.5">
                          <Progress value={p.progress} className="h-1.5 flex-1" />
                          <span className="w-8 text-right text-xs tabular-nums text-muted-foreground">
                            {p.progress}%
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="hidden text-right sm:table-cell">
                        <div className="flex items-center justify-end gap-2">
                          <Avatar className="size-6">
                            <AvatarFallback className={cn(p.owner.color, "text-[9px] text-white")}>
                              {p.owner.initials}
                            </AvatarFallback>
                          </Avatar>
                          <span className="hidden text-xs text-muted-foreground xl:block">
                            {p.owner.name.replace("Dr. ", "")}
                          </span>
                        </div>
                      </TableCell>
                    </motion.tr>
                  ))}
                </TableBody>
              </Table>
            </ChartCard>
          </div>

          {/* CTA strip */}
          <FadeUp>
            <div className="relative overflow-hidden rounded-2xl border border-blue-500/20 bg-gradient-to-r from-blue-600/10 via-indigo-600/10 to-violet-600/10 p-6 sm:p-8">
              <div className="pointer-events-none absolute -top-24 right-0 size-64 rounded-full bg-blue-500/10 blur-3xl" />
              <div className="relative flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
                <div>
                  <h3 className="text-lg font-semibold tracking-tight">Run a full landscape analysis</h3>
                  <p className="mt-1 max-w-xl text-sm text-muted-foreground">
                    Deploy the Patent Intelligence Agent on any molecule — summary, owners, expiries,
                    claims and risk scoring in under two minutes.
                  </p>
                </div>
                <Button asChild size="lg">
                  <Link href="/patents">
                    Launch agent <ArrowRight className="size-4" />
                  </Link>
                </Button>
              </div>
            </div>
          </FadeUp>
        </>
      )}
    </div>
  );
}