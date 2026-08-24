"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bot,
  FolderGit2,
  GitBranch,
  LayoutDashboard,
  ListChecks,
  Settings,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import { motion, useReducedMotion } from "framer-motion";

import { useManager } from "@/components/manager/manager-provider";
import { Logo } from "@/components/shared/logo";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: React.ElementType;
  badge?: string;
}

/**
 * Labels are the UI names, not the URLs — the routes are unchanged.
 *
 * Two collisions are fixed here. "Projects" and "Stage Gates" were
 * near-synonyms for genuinely different things (a project is enrolled into a
 * programme by instantiating a template), and there were two separate
 * "Documents": this upload-and-search library, and the per-programme
 * controlled register. Nobody reading the nav could tell which was which.
 */
const navGroups: { title: string; items: NavItem[] }[] = [
  {
    title: "Workspace",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
      { href: "/projects", label: "Portfolio", icon: FolderGit2 },
    ],
  },
  {
    title: "Research",
    items: [
      { href: "/research/new", label: "New Research", icon: Sparkles },
      { href: "/runs", label: "Research Runs", icon: ListChecks },
      { href: "/documents", label: "Knowledge Library", icon: Upload },
    ],
  },
  {
    title: "Development",
    items: [
      { href: "/programmes", label: "Development Programmes", icon: GitBranch },
    ],
  },
  // No Configuration group. Integrations and Notifications are both reached
  // through the Settings link in the footer, which is where somebody looks for
  // configuration - and listing them twice made the sidebar longer without
  // making anything easier to find.
];

function ManagerNavButton({ onNavigate }: { onNavigate: () => void }) {
  const { openManager } = useManager();

  return (
    <button
      type="button"
      onClick={() => {
        openManager();
        onNavigate();
      }}
      className="group flex w-full items-center gap-3 rounded-lg border border-primary/25 bg-primary/[0.06] px-3 py-2.5 text-sm font-medium text-primary transition-colors hover:bg-primary/10"
    >
      <Bot className="size-[18px]" />
      <span className="flex-1 text-left">Manager Agent</span>
      <span className="text-2xs font-normal text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
        Ask
      </span>
    </button>
  );
}

export function Sidebar({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const pathname = usePathname();
  // The active pill slides between nav items via a shared layout animation.
  // For anyone who asked for less motion, it simply appears.
  const reduceMotion = useReducedMotion();

  return (
    <>
      {open && (
        <div
          className="no-print fixed inset-0 z-40 bg-black/40 backdrop-blur-sm lg:hidden"
          onClick={onClose}
        />
      )}
      {/* `no-print` was missing, and this is `fixed inset-y-0` — so the rail
          printed down the left edge of every page of a run report. */}
      <aside
        className={cn(
          "no-print fixed inset-y-0 left-0 z-50 flex w-[264px] flex-col border-r border-sidebar-border bg-sidebar/95 backdrop-blur-xl transition-transform duration-300 lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <div className="flex h-16 items-center justify-between px-5">
          <Link href="/dashboard" onClick={onClose}>
            <Logo />
          </Link>
          <Button
            variant="ghost"
            size="icon-sm"
            className="lg:hidden"
            onClick={onClose}
            aria-label="Close sidebar"
          >
            <X className="size-4" />
          </Button>
        </div>

        <nav className="flex-1 space-y-6 overflow-y-auto px-3 pb-4 pt-2">
          {/* Above the groups rather than inside one. It is not a destination -
              it opens over whatever you are already looking at, which is the
              whole point of it. */}
          <ManagerNavButton onNavigate={onClose} />

          {navGroups.map((group) => (
            <div key={group.title}>
              <p className="px-3 pb-2 text-2xs font-semibold tracking-wider text-muted-foreground uppercase">
                {group.title}
              </p>
              <div className="space-y-0.5">
                {group.items.map((item) => {
                  const active = pathname === item.href || pathname.startsWith(item.href + "/");
                  const Icon = item.icon;
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={onClose}
                      className={cn(
                        "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all",
                        active
                          ? "bg-primary/10 text-primary"
                          : "text-muted-foreground hover:bg-accent hover:text-foreground"
                      )}
                    >
                      {active &&
                        (reduceMotion ? (
                          <span className="absolute inset-0 -z-0 rounded-lg bg-primary/10" />
                        ) : (
                          <motion.span
                            layoutId="sidebar-active"
                            className="absolute inset-0 -z-0 rounded-lg bg-primary/10"
                            transition={{ type: "spring", stiffness: 400, damping: 32 }}
                          />
                        ))}
                      <Icon
                        className={cn(
                          "relative z-10 size-[18px] transition-colors",
                          active ? "text-primary" : "text-muted-foreground group-hover:text-foreground"
                        )}
                      />
                      <span className="relative z-10 flex-1">{item.label}</span>
                      {item.badge && (
                        <Badge
                          variant={item.badge === "BETA" ? "warning" : "info"}
                          className="relative z-10 px-1.5 py-0 text-2xs"
                        >
                          {item.badge}
                        </Badge>
                      )}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        <div className="border-t p-3">
          <Link href="/settings" onClick={onClose}>
            <div className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
              <Settings className="size-[18px]" />
              Settings
            </div>
          </Link>
        </div>
      </aside>
    </>
  );
}