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
    throw new Error(
      "Supabase is not configured. Copy .env.example to .env.local and set " +
        "NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY."
    );
  }

  return createBrowserClient(url, key);
}

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
