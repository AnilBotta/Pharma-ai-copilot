import assert from "node:assert/strict";
import { test } from "node:test";

// Explicit extension: Node's native TypeScript stripping resolves this file
// as ESM, where the specifier is not rewritten for you.
import { cn } from "./utils.ts";

/**
 * These pin tailwind-merge's handling of the scale steps we added ourselves.
 * It groups classes by matching them against its own built-in scales, not by
 * reading our CSS, so a step it does not recognise lands in a neighbouring
 * group and one of the two classes is silently discarded.
 *
 * The two elevation cases below were measured as genuinely broken against
 * bare `twMerge` before the fix. The two font-size cases already behaved
 * correctly — they are here to keep that true, not to fix it. Each test says
 * which it is, so nobody later deletes a real regression guard believing it
 * to be redundant.
 */

test("REGRESSION: an elevation step is not swallowed by a shadow colour", () => {
  // bare twMerge -> "shadow-primary/20"; shadow-e2 vanished.
  const out = cn("shadow-e2", "shadow-primary/20");
  assert.ok(out.includes("shadow-e2"), `lost shadow-e2: "${out}"`);
  assert.ok(out.includes("shadow-primary/20"), `lost the shadow colour: "${out}"`);
});

test("REGRESSION: an elevation step overrides a stock shadow", () => {
  // bare twMerge -> "shadow-sm shadow-e2"; both survived, so shadow-sm won
  // in the cascade and the elevation had no effect.
  assert.equal(cn("shadow-sm", "shadow-e2"), "shadow-e2");
});

test("elevation steps conflict with each other", () => {
  assert.equal(cn("shadow-e1", "shadow-e3"), "shadow-e3");
});

test("guard: a custom font-size step does not swallow the text colour", () => {
  // Already correct before the fix; asserted so it stays correct.
  const out = cn("text-md", "text-muted-foreground");
  assert.ok(out.includes("text-md"), `lost text-md: "${out}"`);
  assert.ok(out.includes("text-muted-foreground"), `lost the colour: "${out}"`);
});

test("guard: custom font sizes conflict with each other and with stock steps", () => {
  assert.equal(cn("text-2xs", "text-md"), "text-md");
  assert.equal(cn("text-md", "text-sm"), "text-sm");
});

test("ordinary merging is unaffected", () => {
  assert.equal(cn("px-2", "px-4"), "px-4");
  assert.equal(cn("text-sm", "font-medium"), "text-sm font-medium");
  assert.equal(cn(false && "hidden", "block"), "block");
});
