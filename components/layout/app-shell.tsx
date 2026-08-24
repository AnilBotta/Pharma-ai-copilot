"use client";

import * as React from "react";

import { useAuth } from "@/components/auth-provider";
import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { ManagerPanel } from "@/components/manager/manager-panel";
import { ManagerProvider } from "@/components/manager/manager-provider";

/**
 * Authenticated application shell.
 *
 * Route protection lives in middleware.ts, which runs before this component
 * exists. The loading gate here is only to avoid a flash of empty chrome while
 * the client reads its session; it is not an access control, and must not be
 * relied on as one.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const { loading } = useAuth();
  const [sidebarOpen, setSidebarOpen] = React.useState(false);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-center">
          <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
            <svg className="size-6 animate-spin" viewBox="0 0 24 24" fill="none">
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-90"
                fill="currentColor"
                d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
              />
            </svg>
          </div>
          <p className="text-sm text-muted-foreground">Loading workspace…</p>
        </div>
      </div>
    );
  }

  return (
    // The Manager Agent is mounted here, above the router outlet, so a
    // conversation survives navigating to the gate it is about.
    <ManagerProvider>
      <div className="relative min-h-screen">
        {/* Both decoration layers are `fixed inset-0` and neither carried
            `no-print`, so they printed as full-page tints behind the report. */}
        <div className="no-print bg-glow pointer-events-none fixed inset-0 -z-10" />
        <div className="no-print pointer-events-none fixed inset-0 -z-10 bg-grid opacity-[0.35] dark:opacity-[0.12]" />
        <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
        {/* `print-shell` only zeroes this element's 264px sidebar gutter when
            printing. The gutter comes from `lg:`, which a paper-width viewport
            should not match — but "scale to fit" and landscape can push the
            page box past the breakpoint. */}
        <div className="print-shell flex min-h-screen flex-col lg:pl-[264px]">
          <Topbar onMenuClick={() => setSidebarOpen(true)} />
          {/* `print-area` deliberately does NOT live here. The page that owns
              a printable region owns the class — nesting two of them was what
              collapsed printing before. */}
          <main className="mx-auto w-full max-w-[1440px] flex-1 px-4 py-6 sm:px-6 md:py-7 lg:px-8 lg:py-8">
            {children}
          </main>
        </div>
        <ManagerPanel />
      </div>
    </ManagerProvider>
  );
}
