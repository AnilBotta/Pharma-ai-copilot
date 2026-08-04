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
          className="rounded bg-muted px-1 py-0.5 font-mono text-[0.9em]"
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    return <React.Fragment key={`${keyPrefix}-t-${i}`}>{part}</React.Fragment>;
  });
}

export function LightMarkdown({ content }: { content: string }) {
  const lines = content.split("\n");
  const blocks: React.ReactNode[] = [];
  let listBuffer: { type: "ul" | "ol"; items: string[] } | null = null;
  let key = 0;

  const flushList = () => {
    if (!listBuffer) return;
    const items = listBuffer.items.map((item, i) => (
      <li key={i} className="flex gap-2">
        {listBuffer!.type === "ul" ? (
          <span className="mt-[7px] size-1.5 shrink-0 rounded-full bg-blue-500/70" />
        ) : (
          <span className="mt-[1px] w-5 shrink-0 text-right font-medium text-blue-600 dark:text-blue-400 tabular-nums">
            {i + 1}.
          </span>
        )}
        <span>{renderInline(item, `li-${key}-${i}`)}</span>
      </li>
    ));
    blocks.push(
      <div
        key={`list-${key++}`}
        className={listBuffer.type === "ul" ? "space-y-1.5" : "space-y-1.5"}
      >
        {items}
      </div>
    );
    listBuffer = null;
  };

  lines.forEach((raw) => {
    const line = raw.trim();
    if (!line) {
      flushList();
      return;
    }
    const ulMatch = line.match(/^[-•]\s+(.*)/);
    const olMatch = line.match(/^\d+[.)]\s+(.*)/);
    if (ulMatch || olMatch) {
      const type = ulMatch ? "ul" : "ol";
      if (!listBuffer || listBuffer.type !== type) {
        flushList();
        listBuffer = { type, items: [] };
      }
      listBuffer.items.push((ulMatch ?? olMatch)![1]);
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