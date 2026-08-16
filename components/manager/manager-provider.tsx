"use client";

/**
 * Makes the Manager Agent reachable from anywhere in the application.
 *
 * The panel is mounted once at the app layout rather than per page, for a
 * reason that only shows up in use: a conversation you are halfway through
 * must survive navigating to the gate you are asking about. Mounted per page it
 * would unmount on every route change and take the thread with it.
 *
 * `openManager(seed)` lets a page hand over a starting question - "what is
 * holding up this gate" from the gate you are looking at - so the common case
 * needs no typing.
 */

import * as React from "react";

interface ManagerContextValue {
  open: boolean;
  openManager: (seedQuestion?: string) => void;
  closeManager: () => void;
  /** Consumed once by the panel, then cleared. */
  seed: string | null;
  clearSeed: () => void;
}

const ManagerContext = React.createContext<ManagerContextValue | null>(null);

export function ManagerProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = React.useState(false);
  const [seed, setSeed] = React.useState<string | null>(null);

  const value = React.useMemo<ManagerContextValue>(
    () => ({
      open,
      seed,
      openManager: (seedQuestion?: string) => {
        if (seedQuestion) setSeed(seedQuestion);
        setOpen(true);
      },
      closeManager: () => setOpen(false),
      clearSeed: () => setSeed(null),
    }),
    [open, seed]
  );

  return (
    <ManagerContext.Provider value={value}>{children}</ManagerContext.Provider>
  );
}

export function useManager(): ManagerContextValue {
  const ctx = React.useContext(ManagerContext);
  if (!ctx) {
    throw new Error("useManager must be used inside a ManagerProvider.");
  }
  return ctx;
}
