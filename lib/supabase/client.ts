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
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!url || !key) {
    throw new Error(
      "Supabase is not configured. Copy .env.example to .env.local and set " +
        "NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY."
    );
  }

  return createBrowserClient(url, key);
}
