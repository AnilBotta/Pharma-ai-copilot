"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { ChevronDown, ChevronRight, LogOut, Menu, Moon, Plug, Sun } from "lucide-react";

import { useAuth } from "@/components/auth-provider";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";

/**
 * Labels for the first segment of a route.
 *
 * These are the UI names, which deliberately differ from the URLs: "Projects"
 * and "Stage Gates" were near-synonyms for different things, and there were
 * two separate "Documents". The routes are unchanged — only what people read.
 */
const SEGMENT_LABELS: Record<string, string> = {
  dashboard: "Dashboard",
  projects: "Portfolio",
  programmes: "Development Programmes",
  research: "Research",
  new: "New Research",
  runs: "Research Runs",
  documents: "Knowledge Library",
  integrations: "Integrations",
  settings: "Settings",
  notifications: "Notifications",
  gates: "Gate",
  schedule: "Schedule",
};

/** A path segment that is an id rather than a name. */
const IS_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type Crumb = { label: string; href: string };

/**
 * Build a trail from the URL.
 *
 * Id segments are dropped rather than printed: a raw UUID in a breadcrumb is
 * noise, and the record it names is already the <h1> immediately below. The
 * nested document register keeps its own label so it is not confused with the
 * top-level upload library.
 */
function crumbsFor(pathname: string): Crumb[] {
  const parts = pathname.split("/").filter(Boolean);
  const out: Crumb[] = [];
  let href = "";

  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];
    href += `/${part}`;
    if (IS_ID.test(part)) continue;

    let label = SEGMENT_LABELS[part] ?? part.replace(/-/g, " ");
    // /programmes/<id>/documents is the controlled register, not the library.
    if (part === "documents" && i > 0) label = "Controlled Documents";
    out.push({ label, href });
  }
  return out;
}

export function Topbar({ onMenuClick }: { onMenuClick: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, displayName, initials, signOut } = useAuth();
  const { resolvedTheme, setTheme } = useTheme();

  // next-themes cannot know the resolved theme until it has run on the
  // client. Rendering the icon before then printed a Moon on every first
  // paint, including for people already in dark mode, who saw it flip.
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);

  const crumbs = crumbsFor(pathname);

  return (
    <header className="no-print sticky top-0 z-30 flex h-16 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur-xl sm:px-6">
      <Button
        variant="ghost"
        size="icon"
        className="lg:hidden"
        onClick={onMenuClick}
        aria-label="Open sidebar"
      >
        <Menu className="size-5" />
      </Button>

      {/* A trail, not a heading. The page's own <h1> lives in PageHeader. */}
      <nav aria-label="Breadcrumb" className="hidden min-w-0 sm:block">
        <ol className="flex items-center gap-1.5 text-sm text-muted-foreground">
          {crumbs.map((crumb, i) => {
            const last = i === crumbs.length - 1;
            return (
              <li key={crumb.href} className="flex min-w-0 items-center gap-1.5">
                {i > 0 && (
                  <ChevronRight
                    aria-hidden="true"
                    className="size-3.5 shrink-0 opacity-50"
                  />
                )}
                {last ? (
                  <span
                    aria-current="page"
                    className="truncate font-medium text-foreground"
                  >
                    {crumb.label}
                  </span>
                ) : (
                  <Link
                    href={crumb.href}
                    className="truncate transition-colors hover:text-foreground"
                  >
                    {crumb.label}
                  </Link>
                )}
              </li>
            );
          })}
        </ol>
      </nav>

      <div className="ml-auto flex items-center gap-1.5">
        <Button
          variant="ghost"
          size="icon"
          aria-label={
            mounted
              ? `Switch to ${resolvedTheme === "dark" ? "light" : "dark"} theme`
              : "Toggle theme"
          }
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
        >
          {/* Reserve the space but draw nothing until the theme is known, so
              the icon never renders wrong and then corrects itself. */}
          {!mounted ? (
            <span className="size-[18px]" />
          ) : resolvedTheme === "dark" ? (
            <Sun className="size-[18px]" />
          ) : (
            <Moon className="size-[18px]" />
          )}
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              className="ml-1 flex items-center gap-2 rounded-full p-1 transition-colors hover:bg-accent"
              aria-label="Account menu"
            >
              <Avatar className="size-8">
                <AvatarFallback className="bg-primary/15 text-primary">
                  {initials}
                </AvatarFallback>
              </Avatar>
              <ChevronDown className="hidden size-3.5 text-muted-foreground sm:block" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-60">
            <DropdownMenuLabel>
              <div className="flex flex-col">
                <span className="text-sm font-medium">{displayName}</span>
                <span className="text-xs font-normal text-muted-foreground">
                  {user?.email}
                </span>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => router.push("/integrations")}>
              <Plug className="size-4" /> Integrations
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onClick={() => void signOut()}>
              <LogOut className="size-4" /> Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
