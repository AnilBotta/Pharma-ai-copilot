"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  FolderGit2,
  GitBranch,
  LayoutDashboard,
  ListChecks,
  Plug,
  Settings,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import { motion } from "framer-motion";

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

const navGroups: { title: string; items: NavItem[] }[] = [
  {
    title: "Workspace",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
      { href: "/projects", label: "Projects", icon: FolderGit2 },
    ],
  },
  {
    title: "Research",
    items: [
      { href: "/research/new", label: "New Research", icon: Sparkles },
      { href: "/runs", label: "Research Runs", icon: ListChecks },
      { href: "/documents", label: "Documents", icon: Upload },
    ],
  },
  {
    title: "Development",
    items: [{ href: "/programmes", label: "Stage Gates", icon: GitBranch }],
  },
  {
    title: "Configuration",
    items: [{ href: "/integrations", label: "Integrations", icon: Plug }],
  },
];

export function Sidebar({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const pathname = usePathname();

  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm lg:hidden"
          onClick={onClose}
        />
      )}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-[264px] flex-col border-r bg-sidebar/95 backdrop-blur-xl transition-transform duration-300 lg:translate-x-0",
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
          {navGroups.map((group) => (
            <div key={group.title}>
              <p className="px-3 pb-2 text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">
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
                      {active && (
                        <motion.span
                          layoutId="sidebar-active"
                          className="absolute inset-0 -z-0 rounded-lg bg-primary/10"
                          transition={{ type: "spring", stiffness: 400, damping: 32 }}
                        />
                      )}
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
                          className="relative z-10 px-1.5 py-0 text-[10px]"
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
          <Link href="/settings">
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