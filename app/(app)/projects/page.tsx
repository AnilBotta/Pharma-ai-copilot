"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { FolderGit2, Plus, Search, SlidersHorizontal } from "lucide-react";

import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { PriorityBadge, StatusBadge } from "@/components/shared/status-badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { projects } from "@/lib/data";
import { cn, formatDate } from "@/lib/utils";
import type { Project, ProjectPriority, ProjectStatus } from "@/lib/types";

const statuses: ("All" | ProjectStatus)[] = ["All", "Active", "Planning", "On Hold", "Completed"];
const priorities: ("All" | ProjectPriority)[] = ["All", "Critical", "High", "Medium", "Low"];

export default function ProjectsPage() {
  const [query, setQuery] = React.useState("");
  const [status, setStatus] = React.useState<(typeof statuses)[number]>("All");
  const [priority, setPriority] = React.useState<(typeof priorities)[number]>("All");

  const filtered = projects.filter((p) => {
    const q = query.toLowerCase();
    const matchesQuery =
      !q ||
      p.name.toLowerCase().includes(q) ||
      p.code.toLowerCase().includes(q) ||
      p.molecule.toLowerCase().includes(q) ||
      p.indication.toLowerCase().includes(q);
    const matchesStatus = status === "All" || p.status === status;
    const matchesPriority = priority === "All" || p.priority === priority;
    return matchesQuery && matchesStatus && matchesPriority;
  });

  const activeCount = projects.filter((p) => p.status === "Active").length;
  const criticalCount = projects.filter((p) => p.priority === "Critical").length;
  const avgProgress = Math.round(projects.reduce((acc, p) => acc + p.progress, 0) / projects.length);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Projects"
        description="Track drug development programs across discovery, preclinical and clinical phases."
        icon={FolderGit2}
        actions={
          <Button onClick={() => {}}>
            <Plus className="size-4" /> New project
          </Button>
        }
      />

      {/* Stats strip */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="grid gap-4 sm:grid-cols-3"
      >
        {[
          { label: "Active programs", value: activeCount },
          { label: "Critical priority", value: criticalCount },
          { label: "Avg. progress", value: `${avgProgress}%` },
        ].map((s, i) => (
          <div key={s.label} className="glass rounded-xl p-4">
            <p className="text-xs text-muted-foreground">{s.label}</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{s.value}</p>
          </div>
        ))}
      </motion.div>

      {/* Filters */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.05 }}
        className="no-print flex flex-col gap-3 sm:flex-row sm:items-center"
      >
        <div className="relative flex-1 sm:max-w-xs">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by name, code or molecule…"
            className="pl-9"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SlidersHorizontal className="size-4 text-muted-foreground" />
          <Select value={status} onValueChange={(v) => setStatus(v as (typeof statuses)[number])}>
            <SelectTrigger className="w-[140px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {statuses.map((s) => (
                <SelectItem key={s} value={s}>{s === "All" ? "All statuses" : s}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={priority} onValueChange={(v) => setPriority(v as (typeof priorities)[number])}>
            <SelectTrigger className="w-[140px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {priorities.map((p) => (
                <SelectItem key={p} value={p}>{p === "All" ? "All priorities" : p}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </motion.div>

      {/* Table */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, delay: 0.1 }}
        className="overflow-hidden rounded-xl border bg-card"
      >
        {filtered.length === 0 ? (
          <EmptyState
            icon={FolderGit2}
            title="No projects match your filters"
            description="Try clearing the search query or widening the status filter."
            actionLabel="Clear filters"
            onAction={() => {
              setQuery("");
              setStatus("All");
              setPriority("All");
            }}
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Project</TableHead>
                <TableHead className="hidden md:table-cell">Phase</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Priority</TableHead>
                <TableHead className="w-[190px]">Progress</TableHead>
                <TableHead className="hidden lg:table-cell">Created</TableHead>
                <TableHead className="hidden xl:table-cell">Owner</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((p: Project, index) => (
                <motion.tr
                  key={p.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.04, duration: 0.3 }}
                  className="cursor-pointer transition-colors hover:bg-muted/50"
                >
                  <TableCell>
                    <div className="flex items-center gap-3">
                      <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-blue-500/15 bg-gradient-to-br from-blue-600/10 to-violet-600/10 text-blue-600 dark:text-blue-400">
                        <FolderGit2 className="size-4" />
                      </div>
                      <div className="min-w-0">
                        <p className="max-w-[280px] truncate font-medium">{p.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {p.code} · {p.molecule}
                        </p>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="hidden md:table-cell">
                    <Badge variant="secondary">{p.phase}</Badge>
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={p.status} />
                  </TableCell>
                  <TableCell>
                    <PriorityBadge priority={p.priority} />
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2.5">
                      <Progress
                        value={p.progress}
                        className="h-1.5 flex-1"
                        indicatorClassName={
                          p.status === "Completed"
                            ? "bg-emerald-500"
                            : p.priority === "Critical"
                              ? "bg-rose-500"
                              : undefined
                        }
                      />
                      <span className="w-8 text-right text-xs tabular-nums text-muted-foreground">
                        {p.progress}%
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="hidden text-xs text-muted-foreground lg:table-cell">
                    {formatDate(p.created)}
                  </TableCell>
                  <TableCell className="hidden xl:table-cell">
                    <div className="flex items-center gap-2">
                      <Avatar className="size-6">
                        <AvatarFallback className={cn(p.owner.color, "text-[9px] text-white")}>
                          {p.owner.initials}
                        </AvatarFallback>
                      </Avatar>
                      <span className="text-xs text-muted-foreground">{p.owner.name}</span>
                    </div>
                  </TableCell>
                </motion.tr>
              ))}
            </TableBody>
          </Table>
        )}
        <div className="flex items-center justify-between border-t px-4 py-3 text-xs text-muted-foreground">
          <span>
            Showing {filtered.length} of {projects.length} projects
          </span>
          <span>Last updated {formatDate("2026-08-02")}</span>
        </div>
      </motion.div>
    </div>
  );
}