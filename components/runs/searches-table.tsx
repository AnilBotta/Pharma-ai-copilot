"use client";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import type { SearchQuery } from "@/lib/api";

/**
 * The searches a run executed, as a table.
 *
 * Nineteen bordered cards, each with its own internal flex layout, is the
 * wrong shape for nineteen rows of the same five fields: nothing lines up, so
 * "which provider returned nothing" cannot be answered by scanning. A table
 * lines the columns up, which is the entire question this tab exists to
 * answer. `components/ui/table.tsx` had been in the repo unused.
 *
 * Failed searches are marked in the row rather than only in a trailing line,
 * because a query that returned zero results and a query that never ran are
 * different facts and used to look alike.
 */
export function SearchesTable({ queries }: { queries: SearchQuery[] }) {
  if (queries.length === 0) {
    return (
      <p className="rounded-lg border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
        No searches were recorded for this run.
      </p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Provider</TableHead>
          <TableHead className="w-full">Query</TableHead>
          <TableHead className="text-right">Results</TableHead>
          <TableHead className="text-right">Time</TableHead>
          <TableHead>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {queries.map((q) => {
          const failed = q.status !== "ok";
          return (
            <TableRow key={q.id} className={failed ? "bg-danger-surface" : ""}>
              <TableCell className="align-top">
                <span className="type-mono text-xs">{q.provider}</span>
              </TableCell>
              <TableCell className="w-full max-w-0 align-top whitespace-normal">
                <span className="type-mono text-xs break-words">
                  {q.query_text}
                </span>
                {q.error && (
                  <p className="mt-1 text-2xs text-danger">{q.error}</p>
                )}
              </TableCell>
              <TableCell className="align-top text-right">
                <span className="metric text-xs">
                  {failed ? "—" : (q.result_count ?? 0)}
                </span>
              </TableCell>
              <TableCell className="align-top text-right">
                <span className="metric text-xs text-muted-foreground">
                  {q.duration_ms === null ? "—" : `${q.duration_ms} ms`}
                </span>
              </TableCell>
              <TableCell className="align-top">
                <div className="flex items-center gap-1.5">
                  {failed ? (
                    <Badge variant="destructive">{q.status}</Badge>
                  ) : q.result_count === 0 ? (
                    // Zero results is a successful search that found nothing.
                    // Reporting it as plain "ok" hides the one outcome a
                    // reader of this tab is usually hunting for.
                    <Badge variant="warning">no results</Badge>
                  ) : (
                    <Badge variant="success">ok</Badge>
                  )}
                  {q.from_cache && <Badge variant="muted">cached</Badge>}
                </div>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
