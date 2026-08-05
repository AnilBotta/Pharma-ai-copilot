"use client";

import { Upload } from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { Card, CardContent } from "@/components/ui/card";

/**
 * Document upload is stage 8 and is not implemented yet.
 *
 * This page says so plainly rather than presenting a non-functional upload
 * control. A file picker that silently does nothing would be exactly the kind
 * of thing this rebuild exists to remove.
 */
export default function DocumentsPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Documents"
        description="Internal materials you upload become a separate, clearly labelled class of evidence."
        icon={Upload}
      />

      <Card>
        <CardContent className="py-12 text-center">
          <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
            <Upload className="size-6" />
          </div>
          <p className="text-sm font-medium">Document upload is not available yet</p>
          <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
            PDF and text upload with page-anchored citations is planned but not
            built. Rather than show an upload control that does nothing, this
            page states its status.
          </p>
          <p className="mx-auto mt-4 max-w-md text-xs text-muted-foreground">
            When it ships, uploaded content will be treated as untrusted input,
            kept distinct from external scientific and patent evidence, and cited
            with document name and page number.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
