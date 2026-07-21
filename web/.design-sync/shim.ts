// design-sync load-first shim: the browser has no `process`, but the console
// source reads process.env.NEXT_PUBLIC_API_BASE (only inside functions). esbuild
// replaces process.env.NODE_ENV but leaves other keys, so define an empty env
// here — imported first in entry.tsx so it runs before any component evaluates.
declare global {
  // eslint-disable-next-line no-var
  var process: { env: Record<string, string | undefined> };
}
(globalThis as unknown as { process?: { env: Record<string, string | undefined> } }).process ??= { env: {} };
export {};
