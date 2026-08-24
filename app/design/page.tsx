import { notFound } from "next/navigation";

import { Gallery } from "@/app/design/gallery";

/**
 * The design system, rendered against fixtures.
 *
 * WHY THIS EXISTS
 *
 * Every other screen in this app is behind a login, and nobody should be
 * handing a password to an agent — so until now the only way to check a token
 * change was to ask a person to look. This page needs no session, which makes
 * the design system verifiable directly: both themes, every variant, and
 * contrast ratios measured live rather than transcribed.
 *
 * It is also the regression test for the one rule that matters. The readiness
 * section renders 96%-not-ready beside 87.5%-ready. If the higher number ever
 * stops being the amber one, something has broken the product's central claim,
 * and it will be visible here in one glance.
 *
 * DEVELOPMENT ONLY, GUARDED TWICE
 *
 * `notFound()` below, and `middleware.ts` only adds `/design` to its public
 * paths outside production. Two independent guards because a development
 * surface reachable on a deployment is a real mistake, not a tidy one — and
 * because either guard alone could be edited away by someone who did not know
 * about the other.
 */
export const dynamic = "force-static";

export default function DesignPage() {
  if (process.env.NODE_ENV === "production") notFound();

  return (
    <main className="min-h-screen bg-background">
      <div className="grid lg:grid-cols-2">
        <Gallery dark={false} />
        {/* A scoped dark region. Works because the dark variant matches the
            element itself, not only its descendants. */}
        <div className="dark border-t lg:border-t-0 lg:border-l">
          <Gallery dark />
        </div>
      </div>
    </main>
  );
}
