"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertCircle, Loader2, Mail } from "lucide-react";

import { useAuth } from "@/components/auth-provider";
import { Logo } from "@/components/shared/logo";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { GENERAL_DISCLAIMER } from "@/lib/agents";

function LoginForm() {
  const { signIn, signUp, configError } = useAuth();
  const router = useRouter();
  const params = useSearchParams();

  const [mode, setMode] = React.useState<"signin" | "signup">("signin");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    setBusy(true);

    try {
      if (mode === "signup") {
        const { needsConfirmation } = await signUp(email, password);
        if (needsConfirmation) {
          setNotice(
            "Account created. Check your email for a confirmation link, then sign in."
          );
          setMode("signin");
          return;
        }
      } else {
        await signIn(email, password);
      }
      router.push(params.get("next") ?? "/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        <div className="mb-8 flex justify-center">
          <Logo />
        </div>

        <Card>
          <CardContent className="pt-6">
            <h1 className="text-xl font-semibold">
              {mode === "signin" ? "Sign in" : "Create an account"}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Pharma R&amp;D Copilot research workspace.
            </p>

            <form onSubmit={handleSubmit} className="mt-6 space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="scientist@example.com"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete={
                    mode === "signin" ? "current-password" : "new-password"
                  }
                  required
                  minLength={8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="At least 8 characters"
                />
              </div>

              {/* A deployment missing its public Supabase values would
                  otherwise show a generic failure only after someone tried to
                  sign in. Say so up front, and say what to do about it. */}
              {configError && (
                <div
                  role="alert"
                  className="flex items-start gap-2 rounded-lg border border-warning-border bg-warning-surface p-3 text-sm text-warning"
                >
                  <AlertCircle className="mt-0.5 size-4 shrink-0" />
                  <span>{configError}</span>
                </div>
              )}

              {error && (
                <div
                  role="alert"
                  className="flex items-start gap-2 rounded-lg border border-danger-border bg-danger-surface p-3 text-sm text-danger"
                >
                  <AlertCircle className="mt-0.5 size-4 shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              {notice && (
                <div
                  role="status"
                  className="flex items-start gap-2 rounded-lg border border-info-border bg-info-surface p-3 text-sm text-info"
                >
                  <Mail className="mt-0.5 size-4 shrink-0" />
                  <span>{notice}</span>
                </div>
              )}

              <Button type="submit" className="w-full gap-2" disabled={busy}>
                {busy && <Loader2 className="size-4 animate-spin" />}
                {mode === "signin" ? "Sign in" : "Create account"}
              </Button>
            </form>

            <p className="mt-4 text-center text-sm text-muted-foreground">
              {mode === "signin" ? (
                <>
                  No account?{" "}
                  <button
                    type="button"
                    className="font-medium text-primary hover:underline"
                    onClick={() => {
                      setMode("signup");
                      setError(null);
                    }}
                  >
                    Create one
                  </button>
                </>
              ) : (
                <>
                  Already have an account?{" "}
                  <button
                    type="button"
                    className="font-medium text-primary hover:underline"
                    onClick={() => {
                      setMode("signin");
                      setError(null);
                    }}
                  >
                    Sign in
                  </button>
                </>
              )}
            </p>
          </CardContent>
        </Card>

        <p className="mt-6 text-center text-xs leading-relaxed text-muted-foreground">
          {GENERAL_DISCLAIMER}
        </p>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <React.Suspense fallback={null}>
      <LoginForm />
    </React.Suspense>
  );
}
