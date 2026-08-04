"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import type { UserProfile } from "@/lib/types";

/**
 * TRANSITIONAL — NOT SECURE. Replaced by Supabase Auth in stage 7.
 *
 * This still keeps session state in `localStorage`, which means identity is
 * client-controlled and there is no server-side authorisation. It is retained
 * only so the application compiles between the removal of the demo fixtures
 * (stage 1) and the creation of the Supabase project (stage 2).
 *
 * Findings S1 and S2 in docs/CURRENT_SYSTEM_AUDIT.md describe the problem.
 * Do not deploy this file. Do not put real data behind it.
 *
 * What changed from the original: it no longer imports a fabricated user and
 * organisation from `lib/data.ts`, and the stored value is now shape-validated
 * instead of being `JSON.parse`-cast to a trusted type.
 */

const AUTH_KEY = "pharma-copilot-auth";

interface AuthState {
  user: UserProfile;
}

interface AuthContextValue extends AuthState {
  isAuthenticated: boolean;
  login: (email: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = React.createContext<AuthContextValue | null>(null);

const ANONYMOUS: UserProfile = {
  name: "",
  email: "",
  title: "",
  department: "",
  initials: "",
  avatarColor: "bg-muted",
};

/** Validate rather than cast — a stored value is untrusted input. */
function parseStoredAuth(raw: string): AuthState | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return null;
    const user = (parsed as { user?: unknown }).user;
    if (typeof user !== "object" || user === null) return null;
    const email = (user as { email?: unknown }).email;
    if (typeof email !== "string" || !email.includes("@")) return null;
    const name = (user as { name?: unknown }).name;
    return {
      user: {
        ...ANONYMOUS,
        email,
        name: typeof name === "string" ? name : email,
        initials: email.slice(0, 2).toUpperCase(),
      },
    };
  } catch {
    return null;
  }
}

function readStoredAuth(): AuthState | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(AUTH_KEY);
  return raw ? parseStoredAuth(raw) : null;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = React.useState<AuthState | null>(null);
  const [ready, setReady] = React.useState(false);

  React.useEffect(() => {
    setState(readStoredAuth());
    setReady(true);
  }, []);

  const login = React.useCallback(async (email: string) => {
    const next: AuthState = {
      user: {
        ...ANONYMOUS,
        email,
        name: email.split("@")[0],
        initials: email.slice(0, 2).toUpperCase(),
      },
    };
    window.localStorage.setItem(AUTH_KEY, JSON.stringify(next));
    setState(next);
  }, []);

  const logout = React.useCallback(() => {
    window.localStorage.removeItem(AUTH_KEY);
    setState(null);
  }, []);

  const value = React.useMemo<AuthContextValue>(
    () => ({
      user: state?.user ?? ANONYMOUS,
      isAuthenticated: state !== null,
      login,
      logout,
    }),
    [state, login, logout]
  );

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-center">
          <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
            <svg className="size-6 animate-spin" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-90" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
            </svg>
          </div>
          <p className="text-sm text-muted-foreground">Loading session…</p>
        </div>
      </div>
    );
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = React.useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function useRequireAuth() {
  const { isAuthenticated } = useAuth();
  const router = useRouter();

  React.useEffect(() => {
    if (!isAuthenticated) {
      router.replace("/login");
    }
  }, [isAuthenticated, router]);

  return isAuthenticated;
}
