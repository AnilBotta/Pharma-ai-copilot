"use client";

import * as React from "react";

import { useRequireAuth } from "@/components/auth-provider";
import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";

export function AppShell({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useRequireAuth();
  const [sidebarOpen, setSidebarOpen] = React.useState(false);

  if (!isAuthenticated) return null;

  return (
    <div className="relative min-h-screen">
      <div className="bg-glow pointer-events-none fixed inset-0 -z-10" />
      <div className="pointer-events-none fixed inset-0 -z-10 bg-grid opacity-[0.35] dark:opacity-[0.12]" />
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="flex min-h-screen flex-col lg:pl-[264px]">
        <Topbar onMenuClick={() => setSidebarOpen(true)} />
        <main className="mx-auto w-full max-w-[1440px] flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8 print-area">
          {children}
        </main>
      </div>
    </div>
  );
}