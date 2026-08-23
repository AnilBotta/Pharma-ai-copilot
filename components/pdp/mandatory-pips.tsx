import { cn } from "@/lib/utils";

/**
 * The mandatory requirements, drawn one pip each.
 *
 * This exists because readiness is NOT a percentage threshold, and drawing one
 * would be a lie. Gate 1 is ready at 94.4%, Gate 7 at 87.5%, Gate 3 at 89.5% —
 * because what decides readiness is whether every *mandatory* requirement is
 * satisfied, and the percentage is weighted across optional work too. A marker
 * on the percentage axis would invent a threshold that does not exist.
 *
 * So the dispositive quantity gets drawn directly. Seven pips, four filled,
 * three outstanding: that is the verdict, and it is countable at a glance in a
 * way "17.6%" is not. The bar beside it remains what it always was — progress,
 * not permission.
 *
 * Backed entirely by `mandatory_count` / `mandatory_satisfied`, which the API
 * already returns on every stage, so this costs no extra request.
 */
export function MandatoryPips({
  satisfied,
  total,
  isReady,
  className,
  label = "Mandatory",
}: {
  satisfied: number;
  total: number;
  isReady: boolean;
  className?: string;
  label?: string;
}) {
  if (total === 0) return null;

  const outstanding = total - satisfied;

  return (
    <div className={cn("flex items-center gap-3", className)}>
      <span className="type-label shrink-0 text-muted-foreground">{label}</span>

      <div
        className="flex min-w-0 flex-1 gap-1"
        role="img"
        aria-label={`${satisfied} of ${total} mandatory requirements satisfied${
          outstanding > 0 ? `, ${outstanding} outstanding` : ""
        }`}
      >
        {Array.from({ length: total }).map((_, i) => (
          <span
            key={i}
            aria-hidden="true"
            className={cn(
              "h-2.5 min-w-1.5 flex-1 rounded-sm border transition-colors",
              i < satisfied
                ? isReady
                  ? "border-transparent bg-success-solid"
                  : "border-transparent bg-warning-solid"
                : "border-border bg-transparent"
            )}
          />
        ))}
      </div>

      <span className="shrink-0 text-2xs tabular-nums text-muted-foreground">
        {satisfied} of {total}
      </span>
    </div>
  );
}
