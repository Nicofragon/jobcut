// Shared loading / error / skeleton primitives (D2 polish) — consistent across screens.

export function Spinner({ size = 20 }: { size?: number }) {
  return (
    <svg className="motion-safe:animate-spin" width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.2" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-on-surface-faint" role="status" aria-live="polite">
      <span className="text-primary">
        <Spinner />
      </span>
      <span className="text-sm">{label}</span>
    </div>
  );
}

export function ErrorNote({ children }: { children: React.ReactNode }) {
  return (
    <div
      role="alert"
      className="rounded-card border border-[color:var(--color-accent-red)]/40 bg-[color:var(--color-accent-red)]/10 p-4 text-sm text-[color:var(--color-accent-red)]"
    >
      {children}
    </div>
  );
}

// Skeleton placeholders that mirror the real layout while data loads.
export function SkeletonCards({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2" aria-hidden>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded-card border border-border bg-surface p-5 shadow-card">
          <div className="flex justify-between gap-4">
            <div className="flex-1 space-y-2">
              <div className="skeleton h-5 w-2/3 rounded" />
              <div className="skeleton h-4 w-1/3 rounded" />
            </div>
            <div className="skeleton h-12 w-12 rounded-full" />
          </div>
          <div className="mt-4 flex gap-2">
            <div className="skeleton h-6 w-20 rounded-full" />
            <div className="skeleton h-6 w-24 rounded-full" />
          </div>
          <div className="skeleton mt-4 h-16 w-full rounded-lg" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonRows({ count = 4 }: { count?: number }) {
  return (
    <div className="flex flex-col gap-2.5" aria-hidden>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="flex items-center justify-between rounded-card border border-border bg-surface p-4 shadow-card">
          <div className="flex items-center gap-3">
            <div className="skeleton h-11 w-11 rounded-lg" />
            <div className="space-y-2">
              <div className="skeleton h-4 w-40 rounded" />
              <div className="skeleton h-3 w-24 rounded" />
            </div>
          </div>
          <div className="skeleton h-6 w-24 rounded-full" />
        </div>
      ))}
    </div>
  );
}
