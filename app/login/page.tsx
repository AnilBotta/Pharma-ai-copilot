"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { ArrowRight, Eye, EyeOff, FlaskConical, Loader2, Lock, Mail, ShieldCheck, Sparkles } from "lucide-react";

import { useAuth } from "@/components/auth-provider";
import { Logo } from "@/components/shared/logo";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const EASE = [0.22, 1, 0.36, 1] as const;

const featureHighlights = [
  { icon: ShieldCheck, title: "Patent intelligence", text: "FTO, expiry calendars & landscape maps" },
  { icon: FlaskConical, title: "Development strategy", text: "QbD roadmaps, CQAs & risk matrices" },
  { icon: Sparkles, title: "Board-ready reports", text: "PDF & DOCX dossiers in minutes" },
];

export default function LoginPage() {
  const router = useRouter();
  const { login, isAuthenticated } = useAuth();
  const [email, setEmail] = React.useState("anil.bhard@pharmalabs.co");
  const [password, setPassword] = React.useState("demo-password");
  const [remember, setRemember] = React.useState(true);
  const [showPassword, setShowPassword] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (isAuthenticated) router.replace("/dashboard");
  }, [isAuthenticated, router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!email.trim() || password.length < 4) {
      setError("Enter a valid email and password (min 4 characters).");
      return;
    }
    setLoading(true);
    await new Promise((r) => setTimeout(r, 1100));
    await login(email.trim());
    router.replace("/dashboard");
  }

  return (
    <div className="relative flex min-h-screen">
      {/* Ambient background */}
      <div className="bg-glow pointer-events-none fixed inset-0 -z-10" />
      <div className="pointer-events-none fixed inset-0 -z-10 bg-grid opacity-[0.4] dark:opacity-[0.12]" />

      {/* Left showcase panel */}
      <div className="relative hidden flex-1 flex-col justify-between overflow-hidden p-10 lg:flex xl:p-14">
        <motion.div
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: EASE }}
        >
          <Logo size="lg" />
        </motion.div>

        <div className="relative z-10 max-w-lg">
          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.1, ease: EASE }}
          >
            <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-blue-500/25 bg-blue-500/10 px-3 py-1 text-xs font-medium text-blue-600 dark:text-blue-400">
              <span className="relative flex size-2">
                <span className="absolute size-full animate-ping rounded-full bg-blue-500 opacity-60" />
                <span className="relative size-2 rounded-full bg-blue-600" />
              </span>
              AI-native R&D intelligence
            </p>
            <h1 className="text-4xl font-semibold leading-[1.1] tracking-tight xl:text-5xl">
              The AI copilot for{" "}
              <span className="text-gradient">pharmaceutical R&D</span>
            </h1>
            <p className="mt-4 text-base leading-relaxed text-muted-foreground">
              One platform for patent landscapes, literature synthesis, development
              strategy and board-ready reporting — built for pharma, biotech and CDMOs.
            </p>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.25, ease: EASE }}
            className="mt-8 space-y-3"
          >
            {featureHighlights.map((f) => (
              <div
                key={f.title}
                className="glass flex items-center gap-3.5 rounded-xl p-3.5 transition-transform hover:translate-x-1"
              >
                <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-blue-500/20 bg-gradient-to-br from-blue-600/10 to-violet-600/10 text-blue-600 dark:text-blue-400">
                  <f.icon className="size-[18px]" />
                </div>
                <div>
                  <p className="text-sm font-medium">{f.title}</p>
                  <p className="text-xs text-muted-foreground">{f.text}</p>
                </div>
              </div>
            ))}
          </motion.div>
        </div>

        {/* Floating molecules */}
        <div className="pointer-events-none absolute inset-0 overflow-hidden">
          <div className="animate-float-slow absolute top-[22%] right-[10%] size-16 rounded-2xl border border-blue-500/20 bg-blue-500/5 backdrop-blur-sm" />
          <div className="animate-float-slow absolute top-[30%] right-[4%] size-8 rounded-full border border-violet-500/30 bg-violet-500/10 backdrop-blur-sm [animation-delay:1.2s]" />
          <div className="animate-float-slow absolute bottom-[30%] right-[16%] size-5 rounded-full bg-cyan-400/30 blur-[1px] [animation-delay:2.1s]" />
        </div>

        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6 }}
          className="relative z-10 text-xs text-muted-foreground"
        >
          © 2026 Pharma AI Copilot · SOC 2 Type II · GxP-ready deployment options
        </motion.p>
      </div>

      {/* Right auth panel */}
      <div className="flex w-full items-center justify-center px-4 py-10 lg:w-[520px] lg:shrink-0">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: EASE }}
          className="w-full max-w-sm"
        >
          <div className="mb-8 lg:hidden">
            <Logo size="lg" />
          </div>

          <h2 className="text-2xl font-semibold tracking-tight">Welcome back</h2>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Sign in to your R&D workspace
          </p>

          <form onSubmit={handleSubmit} className="mt-8 space-y-5">
            <div className="space-y-2">
              <Label htmlFor="email">Work email</Label>
              <div className="relative">
                <Mail className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="email"
                  type="email"
                  placeholder="you@pharmalabs.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="h-11 pl-9"
                  autoComplete="email"
                />
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="password">Password</Label>
                <Link
                  href="#"
                  onClick={(e) => e.preventDefault()}
                  className="text-xs font-medium text-primary hover:underline"
                >
                  Forgot password?
                </Link>
              </div>
              <div className="relative">
                <Lock className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="h-11 pl-9 pr-10"
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute top-1/2 right-3 -translate-y-1/2 text-muted-foreground transition-colors hover:text-foreground"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Checkbox
                id="remember"
                checked={remember}
                onCheckedChange={(v) => setRemember(v === true)}
              />
              <Label htmlFor="remember" className="font-normal text-muted-foreground">
                Remember me for 30 days
              </Label>
            </div>

            {error && (
              <motion.p
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                className="rounded-lg border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-xs text-rose-600 dark:text-rose-400"
              >
                {error}
              </motion.p>
            )}

            <Button type="submit" size="lg" className="w-full" disabled={loading}>
              {loading ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  Securing session…
                </>
              ) : (
                <>
                  Sign in to workspace
                  <ArrowRight className="size-4" />
                </>
              )}
            </Button>
          </form>

          <div className="mt-8">
            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t" />
              </div>
              <div className="relative flex justify-center">
                <span className="bg-background px-3 text-xs text-muted-foreground">
                  Demo access
                </span>
              </div>
            </div>
            <button
              onClick={() => {
                setEmail("anil.bhard@pharmalabs.co");
                setPassword("demo-password");
              }}
              className="mt-4 w-full rounded-lg border border-dashed border-blue-500/30 bg-blue-500/5 px-4 py-3 text-left text-xs text-muted-foreground transition-colors hover:border-blue-500/50 hover:bg-blue-500/10"
            >
              <span className="font-medium text-blue-600 dark:text-blue-400">
                One-click demo credentials
              </span>{" "}
              — any email & password works in this prototype.
            </button>
          </div>

          <p className="mt-8 text-center text-xs text-muted-foreground lg:hidden">
            © 2026 Pharma AI Copilot · R&D Intelligence Platform
          </p>
        </motion.div>
      </div>
    </div>
  );
}