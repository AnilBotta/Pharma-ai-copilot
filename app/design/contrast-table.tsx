"use client";

import * as React from "react";

/**
 * Live contrast ratios, measured in the browser rather than written down.
 *
 * The tokens are OKLCH and change under `.dark`, so any figure typed into a
 * document is a snapshot that goes stale the moment somebody retunes a token.
 * This resolves the real computed values through a canvas — which is also how
 * you convert an oklch() string to sRGB without a colour library — and reports
 * WCAG AA against them. A number here is true at the moment you are reading it.
 */
const PAIRS: [string, string, string][] = [
  ["Body text", "--foreground", "--background"],
  ["Body text on card", "--foreground", "--card"],
  ["Muted text", "--muted-foreground", "--background"],
  ["Muted text on card", "--muted-foreground", "--card"],
  ["Muted on muted", "--muted-foreground", "--muted"],
  ["Primary on background", "--primary", "--background"],
  ["On primary", "--primary-foreground", "--primary"],
  ["Success on its surface", "--success", "--success-surface"],
  ["Warning on its surface", "--warning", "--warning-surface"],
  ["Danger on its surface", "--danger", "--danger-surface"],
  ["Info on its surface", "--info", "--info-surface"],
  ["Danger on card", "--danger", "--card"],
  ["On success solid", "--success-on-solid", "--success-solid"],
  ["On warning solid", "--warning-on-solid", "--warning-solid"],
  ["On danger solid", "--danger-on-solid", "--danger-solid"],
  ["On info solid", "--info-on-solid", "--info-solid"],
  ["On primary solid", "--primary-foreground", "--primary"],
];

interface Row {
  label: string;
  ratio: number;
}

function measure(scope: HTMLElement): Row[] {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return [];
  const cs = getComputedStyle(scope);

  const rgb = (token: string): [number, number, number] => {
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = cs.getPropertyValue(token).trim() || "#000";
    ctx.fillRect(0, 0, 1, 1);
    const d = ctx.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2]];
  };
  const lin = (v: number) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  const lum = ([r, g, b]: [number, number, number]) =>
    0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);

  return PAIRS.map(([label, fg, bg]) => {
    const a = lum(rgb(fg));
    const b = lum(rgb(bg));
    const hi = Math.max(a, b);
    const lo = Math.min(a, b);
    return { label, ratio: Math.round(((hi + 0.05) / (lo + 0.05)) * 100) / 100 };
  });
}

export function ContrastTable({ dark }: { dark: boolean }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [rows, setRows] = React.useState<Row[]>([]);

  React.useEffect(() => {
    if (ref.current) setRows(measure(ref.current));
  }, [dark]);

  const failing = rows.filter((r) => r.ratio < 4.5).length;

  return (
    <div ref={ref}>
      {rows.length > 0 && (
        <p className="mb-2 text-2xs text-muted-foreground">
          {failing === 0 ? (
            <>All {rows.length} pairs meet WCAG AA (4.5:1).</>
          ) : (
            <span className="text-danger">
              {failing} of {rows.length} pairs are below WCAG AA.
            </span>
          )}
        </p>
      )}
      <table className="w-full text-2xs">
        <thead>
          <tr className="border-b text-muted-foreground">
            <th className="py-1 text-left font-medium">Pair</th>
            <th className="py-1 text-right font-medium">Ratio</th>
            <th className="py-1 text-right font-medium">AA</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className="border-b last:border-0">
              <td className="py-1">{r.label}</td>
              <td className="metric py-1 text-right">{r.ratio.toFixed(2)}</td>
              <td
                className={`py-1 text-right font-medium ${
                  r.ratio >= 4.5 ? "text-success" : "text-danger"
                }`}
              >
                {r.ratio >= 4.5 ? "pass" : "FAIL"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
