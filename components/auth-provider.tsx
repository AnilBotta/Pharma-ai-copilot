"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import type { Session, User } from "@supabase/supabase-js";

import { createClient } from "@/lib/supabase/client";

/**
 * Authentication backed by Supabase Auth.
 *
 * Replaces the prototype's localStorage session, where any email string granted
 * access and identity was a value the user could edit in DevTools (audit
 * findings S1 and S2). Sessions are now cookie-based, verified server-side by
 * middleware before a page renders, and every backend call carries a
 * signature-verified JWT.
 */

interface AuthContextValue {
  user: User | null;
  session: Session | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<{ needsConfirmation: boolean }>;
  signOut: () => Promise<void>;
  displayName: string;
  initials: string;
}

const AuthContext = React.createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = React.useState<Session | null>(null);
  const [loading, setLoading] = React.useState(true);
  const router = useRouter();
  const supabase = React.useMemo(() => createClient(), []);

  React.useEffect(() => {
    let active = true;

    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      setSession(data.session);
      setLoading(false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      setLoading(false);
    });

    return () => {
      active = false;
      subscription.unsubscribe();
    };
  }, [supabase]);

  const signIn = React.useCallback(
    async (email: string, password: string) => {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw new Error(error.message);
      router.refresh();
    },
    [supabase, router]
  );

  const signUp = React.useCallback(
    async (email: string, password: string) => {
      const { data, error } = await supabase.auth.signUp({ email, password });
      if (error) throw new Error(error.message);
      // When email confirmation is enabled the user exists but has no session.
      return { needsConfirmation: !data.session };
    },
    [supabase]
  );

  const signOut = React.useCallback(async () => {
    await supabase.auth.signOut();
    router.push("/login");
    router.refresh();
  }, [supabase, router]);

  const user = session?.user ?? null;
  const email = user?.email ?? "";
  const displayName =
    (user?.user_metadata?.full_name as string | undefined) ||
    (email ? email.split("@")[0] : "");

  const value = React.useMemo<AuthContextValue>(
    () => ({
      user,
      session,
      loading,
      signIn,
      signUp,
      signOut,
      displayName,
      initials: (displayName || email || "?").slice(0, 2).toUpperCase(),
    }),
    [user, session, loading, signIn, signUp, signOut, displayName, email]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = React.useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
