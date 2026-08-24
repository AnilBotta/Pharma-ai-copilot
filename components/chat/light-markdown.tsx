import React from "react";

function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={`${keyPrefix}-b-${i}`} className="font-semibold">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code
          key={`${keyPrefix}-c-${i}`}
          className="type-mono rounded bg-muted px-1 py-0.5 text-[0.9em]"
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    return <React.Fragment key={`${keyPrefix}-t-${i}`}>{part}</React.Fragment>;
  });
}

interface Item {
  depth: number;
  text: string;
}

/**
 * Indentation is carried, not thrown away.
 *
 * Every line used to be `trim()`ed before the bullet match, which flattened
 * nested lists into one level. The Manager Agent demonstrably emits them —
 * seven of sixteen stored answers are lists, and they nest:
 *
 *     - Gate 0 (conditionally approved): blocked by 5 requirements:
 *       - Overdue/no evidence: G0-PM-001, G0-CO-001, …
 *       - Awaiting approval: G0-IP-001 …
 *
 * Flattened, the two sub-lists read as peers of the gate they belong to, which
 * is a different claim about the data.
 *
 * Depth is rendered as an indent rather than as truly nested lists: the visual
 * result is the same for this content and there is no tree to get wrong.
 */
export function LightMarkdown({ content }: { content: string }) {
  const lines = content.split("\n");
  const blocks: React.ReactNode[] = [];
  let listBuffer: { type: "ul" | "ol"; items: Item[] } | null = null;
  let key = 0;

  const flushList = () => {
    if (!listBuffer) return;
    const buf = listBuffer;
    const items = buf.items.map((item, i) => (
      <li
        key={i}
        className="flex gap-2"
        style={{ paddingLeft: `${item.depth * 1.15}rem` }}
      >
        {buf.type === "ul" ? (
          <span
            className={
              item.depth === 0
                ? "mt-[7px] size-1.5 shrink-0 rounded-full bg-primary/70"
                : "mt-[7px] size-1.5 shrink-0 rounded-full border border-primary/60"
            }
          />
        ) : (
          <span className="metric mt-[1px] w-5 shrink-0 text-right text-primary">
            {i + 1}.
          </span>
        )}
        <span className="min-w-0">{renderInline(item.text, `li-${key}-${i}`)}</span>
      </li>
    ));
    blocks.push(
      <ul key={`list-${key++}`} className="space-y-1.5">
        {items}
      </ul>
    );
    listBuffer = null;
  };

  lines.forEach((raw) => {
    const line = raw.trim();
    if (!line) {
      flushList();
      return;
    }
    // Measured from the RAW line, before trimming — this is the bit that used
    // to be discarded. Two spaces per level, which is what the model emits.
    const indent = raw.length - raw.trimStart().length;
    const depth = Math.min(Math.floor(indent / 2), 3);

    const ulMatch = line.match(/^[-•]\s+(.*)/);
    const olMatch = line.match(/^\d+[.)]\s+(.*)/);
    if (ulMatch || olMatch) {
      const type = ulMatch ? "ul" : "ol";
      if (!listBuffer || listBuffer.type !== type) {
        flushList();
        listBuffer = { type, items: [] };
      }
      listBuffer.items.push({ depth, text: (ulMatch ?? olMatch)![1] });
      return;
    }
    flushList();
    if (line.startsWith("### ")) {
      blocks.push(
        <h4 key={key++} className="mt-4 mb-1.5 font-semibold first:mt-0">
          {renderInline(line.slice(4), `h-${key}`)}
        </h4>
      );
      return;
    }
    if (line.startsWith("---")) {
      blocks.push(<div key={key++} className="my-3 h-px bg-border" />);
      return;
    }
    blocks.push(
      <p key={key++} className="leading-relaxed">
        {renderInline(line, `p-${key}`)}
      </p>
    );
  });
  flushList();

  return <div className="space-y-2.5">{blocks}</div>;
}
