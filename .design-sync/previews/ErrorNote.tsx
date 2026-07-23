import { ErrorNote } from "web";

// Inline alert for recoverable failures — red-tinted card, accepts any content.
export function ApiOffline() {
  return (
    <div style={{ maxWidth: 460 }}>
      <ErrorNote>
        Couldn&apos;t reach the jobcut API. Make sure <code>jobcut serve</code> is running,
        then retry.
      </ErrorNote>
    </div>
  );
}

// A short, single-line variant.
export function Short() {
  return (
    <div style={{ maxWidth: 460 }}>
      <ErrorNote>No jobs matched your saved searches today.</ErrorNote>
    </div>
  );
}
