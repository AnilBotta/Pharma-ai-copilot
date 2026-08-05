"use client";

import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { ChevronDown, LogOut, Menu, Moon, Plug, Sun } from "lucide-react";

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

const titles: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/projects": "Projects",
  "/research/new": "New Research",
  "/runs": "Research Runs",
  "/documents": "Documents",
  "/integrations": "Integrations",
};

function titleFor(pathname: string): string {
  if (titles[pathname]) return titles[pathname];
  if (pathname.startsWith("/runs/")) return "Research Run";
  return "Pharma R&D Copilot";
}

export function Topbar({ onMenuClick }: { onMenuClick: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, displayName, initials, signOut } = useAuth();
  const { resolvedTheme, setTheme } = useTheme();

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

      <h1 className="hidden text-sm font-medium text-muted-foreground sm:block">
        {titleFor(pathname)}
      </h1>

      <div className="ml-auto flex items-center gap-1.5">
        <Button
          variant="ghost"
          size="icon"
          aria-label="Toggle theme"
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
        >
          {resolvedTheme === "dark" ? (
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
