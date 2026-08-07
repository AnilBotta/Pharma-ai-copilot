"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import type { Session, User } from "@supabase/supabase-js";

import {
  createClient,
  isSupabaseConfigured,
  SUPABASE_NOT_CONFIGURED,
} from "@/lib/supabase/client";

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
  /** Set when the public Supabase values were missing at build time. */
  configError: string | null;
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

  /**
   * Null when Supabase is unconfigured, rather than throwing.
   *
   * This provider wraps the whole application including the 404 page, and
   * Next.js prerenders those at build time. Throwing here therefore failed the
   * *build* — on a page that needs no authentication at all — with a message
   * about `.env.local` that is misleading on a host like Vercel. A missing
   * public config is a deployment mistake to report at runtime, not a reason
   * for the build to collapse.
   */
  const configured = isSupabaseConfigured();
  const supabase = React.useMemo(
    () => (configured ? createClient() : null),
    [configured]
  );
  const configError = configured ? null : SUPABASE_NOT_CONFIGURED;

  React.useEffect(() => {
    if (!supabase) {
      // Nothing to wait for; resolve so the UI can render its error state.
      setLoading(false);
      return;
    }

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
      if (!supabase) throw new Error(SUPABASE_NOT_CONFIGURED);
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw new Error(error.message);
      router.refresh();
    },
    [supabase, router]
  );

  const signUp = React.useCallback(
    async (email: string, password: string) => {
      if (!supabase) throw new Error(SUPABASE_NOT_CONFIGURED);
      const { data, error } = await supabase.auth.signUp({ email, password });
      if (error) throw new Error(error.message);
      // When email confirmation is enabled the user exists but has no session.
      return { needsConfirmation: !data.session };
    },
    [supabase]
  );

  const signOut = React.useCallback(async () => {
    if (!supabase) throw new Error(SUPABASE_NOT_CONFIGURED);
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
      configError,
      signIn,
      signUp,
      signOut,
      displayName,
      initials: (displayName || email || "?").slice(0, 2).toUpperCase(),
    }),
    [user, session, loading, configError, signIn, signUp, signOut, displayName, email]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = React.useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
