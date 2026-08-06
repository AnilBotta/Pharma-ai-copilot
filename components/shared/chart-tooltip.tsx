type Value = number | string;

interface TooltipEntry {
  dataKey?: string | number;
  name?: string;
  value?: Value;
  color?: string;
  payload?: { fill?: string };
}

interface ChartTooltipProps {
  active?: boolean;
  payload?: TooltipEntry[];
  label?: string;
  formatter?: (value: Value | undefined, name: string) => string;
}

export function ChartTooltip({ active, payload, label, formatter }: ChartTooltipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="glass-strong rounded-lg px-3 py-2 text-xs shadow-xl">
      {label && <p className="mb-1.5 font-semibold">{label}</p>}
      <div className="space-y-1">
        {payload.map((entry, i) => (
          <div key={String(entry.dataKey ?? i)} className="flex items-center gap-2">
            <span
              className="size-2 shrink-0 rounded-full"
              style={{ background: entry.color ?? entry.payload?.fill }}
            />
            <span className="text-muted-foreground">{entry.name}:</span>
            <span className="font-medium">
              {formatter ? formatter(entry.value, entry.name ?? "") : entry.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}