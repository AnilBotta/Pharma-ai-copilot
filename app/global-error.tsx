"use client";

/**
 * The last boundary. This catches failures in the root layout itself — the
 * theme provider, the auth provider — where the shell has not rendered and
 * app/(app)/error.tsx cannot help.
 *
 * It must supply its own <html> and <body>, because it replaces the root
 * layout rather than rendering inside it. That also means it cannot use the
 * app's components or tokens: none of the stylesheet is guaranteed at this
 * point, so the styling here is deliberately inline and self-contained.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "ui-sans-serif, system-ui, sans-serif",
          background: "#fafafa",
          color: "#18181b",
          padding: "24px",
        }}
      >
        <div style={{ maxWidth: "32rem" }}>
          <h1 style={{ fontSize: "1.125rem", fontWeight: 600, margin: 0 }}>
            The application could not start
          </h1>
          <p
            style={{
              marginTop: "0.5rem",
              fontSize: "0.875rem",
              lineHeight: 1.5,
              color: "#52525b",
            }}
          >
            This is a failure in the application shell itself rather than in
            one page. Reloading may clear it. Nothing you did was saved or
            lost.
          </p>
          {error.digest && (
            <p
              style={{
                marginTop: "0.75rem",
                fontFamily: "ui-monospace, monospace",
                fontSize: "0.75rem",
                color: "#71717a",
              }}
            >
              Reference {error.digest}
            </p>
          )}
          <button
            onClick={reset}
            style={{
              marginTop: "1.25rem",
              height: "2.25rem",
              padding: "0 1rem",
              borderRadius: "0.625rem",
              border: "none",
              background: "#4f46e5",
              color: "white",
              fontSize: "0.875rem",
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            Reload
          </button>
        </div>
      </body>
    </html>
  );
}
