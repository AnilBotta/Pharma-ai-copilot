import Link from "next/link";
import { Compass } from "lucide-react";

import { Button } from "@/components/ui/button";

/**
 * Reached by a mistyped URL, or by `notFound()` from a page whose record does
 * not exist. Previously this rendered Next's bare default page with no shell
 * at all, which looks like the application has crashed rather than like a
 * wrong address.
 */
export default function AppNotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 text-center">
      <div className="flex size-12 items-center justify-center rounded-2xl border border-primary/20 bg-primary/8 text-primary">
        <Compass aria-hidden="true" className="size-6" />
      </div>
      <div>
        <h2 className="text-lg font-semibold">There is nothing at this address</h2>
        <p className="mx-auto mt-1 max-w-sm text-sm text-muted-foreground">
          The page may have been removed, or the record it referred to may no
          longer exist.
        </p>
      </div>
      <Button asChild size="sm">
        <Link href="/dashboard">Back to the dashboard</Link>
      </Button>
    </div>
  );
}
