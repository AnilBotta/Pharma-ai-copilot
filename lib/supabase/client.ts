import { createBrowserClient } from "@supabase/ssr";

/**
 * Supabase client for browser code.
 *
 * Uses the publishable (anon) key, which is designed to be public and is
 * constrained by Row Level Security. No service-role key or model credential
 * ever reaches this bundle.
 */
export function createClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = publishableKey();

  if (!url || !key) {
    throw new Error(SUPABASE_NOT_CONFIGURED);
  }

  return createBrowserClient(url, key);
}

/**
 * Whether the public Supabase values were present at build time.
 *
 * `NEXT_PUBLIC_*` values are inlined by static substitution when the bundle is
 * compiled, so this is decided by the *build* environment. Setting them only as
 * runtime variables on a host has no effect — the strings were already baked in
 * as `undefined`.
 */
export function isSupabaseConfigured(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_SUPABASE_URL && publishableKey());
}

export const SUPABASE_NOT_CONFIGURED =
  "Supabase is not configured. Locally, copy .env.example to .env.local. On a " +
  "host such as Vercel, set NEXT_PUBLIC_SUPABASE_URL and " +
  "NEXT_PUBLIC_SUPABASE_ANON_KEY as environment variables and redeploy — they " +
  "are read when the bundle is built, not when it runs.";

/**
 * The public key, under either name.
 *
 * Supabase's own setup snippets now emit
 * `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, while the older and still widely used
 * name is `NEXT_PUBLIC_SUPABASE_ANON_KEY`. They hold the same value. Accepting
 * both means pasting the dashboard's generated `.env.local` just works instead
 * of failing with a confusing "not configured".
 *
 * Both must be referenced as full literals, not built dynamically: Next.js
 * inlines `process.env.NEXT_PUBLIC_*` at build time by static substitution.
 */
export function publishableKey(): string | undefined {
  return (
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ??
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
  );
}
