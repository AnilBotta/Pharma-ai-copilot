import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

/**
 * Server-side route protection.
 *
 * This is the fix for audit finding S1. Previously every route rendered for
 * anonymous requests and a `useEffect` redirect hid the content after it had
 * already been sent; an attacker never needed to defeat the redirect, only to
 * read the response. Now an unauthenticated request to a protected route is
 * redirected before any page content is produced.
 *
 * It also refreshes the Supabase session cookie on each request, which is why
 * it must run on every matched path rather than only on protected ones.
 */

const PUBLIC_PATHS = ["/login", "/auth"];

export async function middleware(request: NextRequest) {
  let response = NextResponse.next({ request });

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  // Either key name; Supabase's snippets use PUBLISHABLE_KEY, older setups
  // use ANON_KEY. Same value.
  const key =
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ??
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

  // Without configuration we cannot verify anyone. Fail closed: send every
  // request to /login rather than letting unauthenticated traffic through.
  if (!url || !key) {
    if (isPublic(request.nextUrl.pathname)) return response;
    return NextResponse.redirect(new URL("/login", request.url));
  }

  const supabase = createServerClient(url, key, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value }) =>
          request.cookies.set(name, value)
        );
        response = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) =>
          response.cookies.set(name, value, options)
        );
      },
    },
  });

  // getUser() revalidates the token with Supabase. getSession() only reads the
  // cookie, which a client controls, so it must not be the basis of an
  // authorisation decision here.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const path = request.nextUrl.pathname;

  if (!user && !isPublic(path)) {
    const redirect = new URL("/login", request.url);
    // Preserve where they were going so login can return them there.
    redirect.searchParams.set("next", path);
    return NextResponse.redirect(redirect);
  }

  if (user && path === "/login") {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return response;
}

function isPublic(path: string): boolean {
  return PUBLIC_PATHS.some((p) => path === p || path.startsWith(`${p}/`));
}

export const config = {
  matcher: [
    /*
     * Every path except static assets, image files, and the API.
     *
     * `api` is excluded because it is not served by Next.js at all: on the
     * deployment it is a Python function holding the whole FastAPI app, which
     * authenticates each request itself with a signature-verified bearer
     * token. Matching it here meant Next intercepted `/api/health`, found no
     * Supabase cookie, and redirected to `/login` — so every API call answered
     * 200 with the sign-in page's HTML instead of JSON. The frontend reported
     * "Cannot reach the API", which points at the backend being down rather
     * than at the request never having left the frontend.
     *
     * Cookie-based route protection and bearer-token API auth are two separate
     * mechanisms guarding two separate surfaces. Running the first over the
     * second does not add security; it only breaks it.
     */
    "/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
