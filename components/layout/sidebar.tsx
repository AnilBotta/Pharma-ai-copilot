"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  FileText,
  FlaskConical,
  LayoutDashboard,
  MessageSquareText,
  Newspaper,
  Projector,
  Settings,
  ShieldCheck,
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
    items: [{ href: "/dashboard", label: "Dashboard", icon: LayoutDashboard }],
  },
  {
    title: "AI Agents",
    items: [
      {
        href: "/chat",
        label: "Research Copilot",
        icon: MessageSquareText,
        badge: "4",
      },
      { href: "/patents", label: "Patent Intelligence", icon: ShieldCheck },
      { href: "/literature", label: "Literature Review", icon: Newspaper },
      {
        href: "/strategy",
        label: "Dev Strategy",
        icon: FlaskConical,
        badge: "BETA",
      },
    ],
  },
  {
    title: "Deliverables",
    items: [
      { href: "/reports", label: "Report Generator", icon: FileText },
      { href: "/projects", label: "Projects", icon: Projector },
    ],
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
          <div className="mt-2 rounded-xl border border-blue-500/20 bg-gradient-to-br from-blue-600/10 to-violet-600/10 p-3">
            <p className="text-[13px] font-medium">Enterprise plan</p>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              42 of 100 agent seats used
            </p>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
              <div className="h-full w-[42%] rounded-full bg-gradient-to-r from-blue-600 to-violet-600" />
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}