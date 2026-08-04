"use client";

import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import {
  Bell,
  ChevronDown,
  Command,
  LogOut,
  Menu,
  Moon,
  Search,
  Settings,
  Sun,
} from "lucide-react";

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
import { cn } from "@/lib/utils";

const titles: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/chat": "Research Copilot",
  "/patents": "Patent Intelligence",
  "/literature": "Literature Review",
  "/strategy": "Development Strategy",
  "/reports": "Report Generator",
  "/projects": "Projects",
  "/settings": "Settings",
};

export function Topbar({ onMenuClick }: { onMenuClick: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
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
        {titles[pathname] ?? "Pharma AI Copilot"}
      </h1>

      <div className="ml-auto flex items-center gap-1.5">
        <button
          className="group hidden items-center gap-2 rounded-lg border border-border/70 bg-card/60 py-1.5 pr-2 pl-3 text-sm text-muted-foreground transition-all hover:border-border hover:bg-card md:flex"
          onClick={() => router.push("/chat")}
        >
          <Search className="size-3.5" />
          <span className="text-xs">Search research…</span>
          <kbd className="ml-4 hidden items-center gap-0.5 rounded border bg-muted px-1.5 py-0.5 text-[10px] font-medium lg:flex">
            <Command className="size-2.5" /> K
          </kbd>
        </button>

        <Button
          variant="ghost"
          size="icon"
          aria-label="Toggle theme"
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
        >
          {resolvedTheme === "dark" ? <Sun className="size-[18px]" /> : <Moon className="size-[18px]" />}
        </Button>

        <Button variant="ghost" size="icon" className="relative" aria-label="Notifications">
          <Bell className="size-[18px]" />
          <span className="absolute top-2 right-2.5 flex size-2">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-blue-500 opacity-60" />
            <span className="relative inline-flex size-2 rounded-full bg-blue-600" />
          </span>
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="ml-1 flex items-center gap-2 rounded-full p-1 transition-colors hover:bg-accent">
              <Avatar className="size-8">
                <AvatarFallback className={cn(user.avatarColor, "text-white")}>
                  {user.initials}
                </AvatarFallback>
              </Avatar>
              <ChevronDown className="hidden size-3.5 text-muted-foreground sm:block" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-60">
            <DropdownMenuLabel>
              <div className="flex flex-col">
                <span className="text-sm font-medium">{user.name}</span>
                <span className="text-xs font-normal text-muted-foreground">{user.email}</span>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => router.push("/settings")}>
              <Settings className="size-4" /> Settings
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              variant="destructive"
              onClick={() => {
                logout();
                router.replace("/login");
              }}
            >
              <LogOut className="size-4" /> Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
