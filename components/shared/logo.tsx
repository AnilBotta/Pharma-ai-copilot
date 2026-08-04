import { cn } from "@/lib/utils";

export function Logo({
  className,
  iconOnly = false,
  size = "md",
}: {
  className?: string;
  iconOnly?: boolean;
  size?: "sm" | "md" | "lg";
}) {
  const iconBox =
    size === "lg" ? "size-11 rounded-2xl" : size === "sm" ? "size-7 rounded-lg" : "size-9 rounded-xl";
  const iconSize = size === "lg" ? "size-6" : size === "sm" ? "size-4" : "size-5";
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <div
        className={cn(
          iconBox,
          "relative flex items-center justify-center bg-gradient-to-br from-blue-600 via-indigo-600 to-violet-600 text-white shadow-lg shadow-blue-600/25"
        )}
      >
        <svg viewBox="0 0 24 24" fill="none" className={iconSize} aria-hidden>
          <path
            d="M4 14a4 4 0 1 0 3.47-3.97A6.5 6.5 0 1 1 15.5 17.5a4 4 0 1 0-4.4-2.55L7.47 11.3A4 4 0 0 0 4 14Z"
            fill="currentColor"
            opacity="0.95"
          />
          <circle cx="4" cy="14" r="1.2" fill="currentColor" />
          <circle cx="15.5" cy="17.5" r="1.2" fill="currentColor" />
        </svg>
        <div className="absolute inset-0 rounded-[inherit] bg-gradient-to-t from-black/10 to-transparent" />
      </div>
      {!iconOnly && (
        <div className="leading-tight">
          <p className={cn("font-semibold tracking-tight", size === "lg" ? "text-lg" : "text-[15px]")}>
            Pharma <span className="text-gradient">AI</span> Copilot
          </p>
          {size === "lg" && (
            <p className="text-[11px] text-muted-foreground">R&D Intelligence Platform</p>
          )}
        </div>
      )}
    </div>
  );
}
