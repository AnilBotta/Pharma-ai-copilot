import { cn } from "@/lib/utils";

/**
 * `animate-shimmer` was defined in globals.css and used by nothing; the
 * skeleton used `animate-pulse` instead. A shimmer reads as "content is on
 * its way", where a pulse reads more like a placeholder that may never fill.
 *
 * Under `prefers-reduced-motion` the base layer flattens the animation to a
 * near-instant single iteration, so this degrades to a static tinted block
 * rather than a moving one.
 */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden="true"
      className={cn("animate-shimmer rounded-md bg-muted", className)}
      {...props}
    />
  );
}

/**
 * A block of text lines rather than one grey slab. The last line is short,
 * because that is what a paragraph looks like, and the difference is most of
 * what makes a loading state read as content rather than as damage.
 */
function SkeletonText({
  lines = 3,
  className,
  ...props
}: React.ComponentProps<"div"> & { lines?: number }) {
  return (
    <div
      data-slot="skeleton-text"
      className={cn("flex flex-col gap-2", className)}
      {...props}
    >
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={cn("h-4", i === lines - 1 && lines > 1 && "w-3/5")}
        />
      ))}
    </div>
  );
}

export { Skeleton, SkeletonText };
