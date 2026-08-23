import { Skeleton, SkeletonText } from "@/components/ui/skeleton";

/**
 * Shown while a route segment's code is being fetched, which is the gap the
 * app had no answer for: navigating to the gate workspace on a slow
 * connection left the previous page frozen with no sign anything was
 * happening.
 *
 * It mirrors the shared page shape — icon chip, title, description, then
 * content — rather than being one grey rectangle, because the difference is
 * most of what makes a loading state read as content arriving rather than as
 * something broken.
 */
export default function AppLoading() {
  return (
    <div className="space-y-8" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading</span>

      <div className="flex items-start gap-3.5">
        <Skeleton className="mt-0.5 size-10 shrink-0 rounded-xl" />
        <div className="w-full max-w-md space-y-2">
          <Skeleton className="h-7 w-1/2" />
          <Skeleton className="h-4 w-4/5" />
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="space-y-3 rounded-xl border p-5">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-7 w-16" />
            <SkeletonText lines={2} />
          </div>
        ))}
      </div>
    </div>
  );
}
