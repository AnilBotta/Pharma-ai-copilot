"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { currentUser, orgProfile } from "@/lib/data";
import type { OrgProfile, UserProfile } from "@/lib/types";

const AUTH_KEY = "pharma-copilot-auth";

interface AuthState {
  user: UserProfile;
  org: OrgProfile;
}

interface AuthContextValue extends AuthState {
  isAuthenticated: boolean;
  login: (email: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = React.createContext<AuthContextValue | null>(null);

function readStoredAuth(): AuthState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(AUTH_KEY);
    return raw ? (JSON.parse(raw) as AuthState) : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = React.useState<AuthState | null>(null);
  const [ready, setReady] = React.useState(false);

  React.useEffect(() => {
    setState(readStoredAuth());
    setReady(true);
  }, []);

  const login = React.useCallback(async (email: string) => {
    const name = currentUser.name;
    const firstName = name.split(" ").slice(0, 2).join(" ");
    const user: UserProfile = {
      ...currentUser,
      name: firstName,
      email,
    };
    const next: AuthState = { user, org: orgProfile };
    window.localStorage.setItem(AUTH_KEY, JSON.stringify(next));
    setState(next);
  }, []);

  const logout = React.useCallback(() => {
    window.localStorage.removeItem(AUTH_KEY);
    setState(null);
  }, []);

  const value = React.useMemo<AuthContextValue>(
    () => ({
      user: state?.user ?? currentUser,
      org: state?.org ?? orgProfile,
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
          <p className="text-sm text-muted-foreground">Securing session…</p>
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
