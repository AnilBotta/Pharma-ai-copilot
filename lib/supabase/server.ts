import { cookies } from "next/headers";
import { createServerClient } from "@supabase/ssr";

/**
 * Supabase client for server components and route handlers.
 *
 * Reads the session from cookies so authentication can be checked on the
 * server, before any page content is sent. The prototype had no equivalent:
 * every page rendered for anonymous requests and relied on a client-side
 * redirect to hide it (audit finding S1).
 */
export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options)
            );
          } catch {
            // Called from a Server Component, where cookies are read-only.
            // Session refresh is handled by middleware instead.
          }
        },
      },
    }
  );
}

/**
 * The access token for the current session, used to authenticate calls to the
 * FastAPI backend. Returns null when there is no session.
 */
export async function getAccessToken(): Promise<string | null> {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return session?.access_token ?? null;
}
