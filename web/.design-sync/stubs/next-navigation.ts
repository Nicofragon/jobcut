// design-sync render stub for next/navigation. The console components read the
// Next app-router from context (useRouter/usePathname), which throws outside a
// running Next app. For standalone preview rendering in Claude Design we return
// inert defaults so the real components mount and look correct; routing is
// app-plumbing the design agent re-wires anyway.
export function usePathname(): string {
  return "/";
}
export function useSearchParams(): URLSearchParams {
  return new URLSearchParams();
}
export function useParams(): Record<string, string> {
  return {};
}
const noop = () => {};
export function useRouter() {
  return {
    push: noop,
    replace: noop,
    back: noop,
    forward: noop,
    refresh: noop,
    prefetch: noop,
  };
}
export function redirect(): never {
  throw new Error("redirect() is not available in preview");
}
export function notFound(): never {
  throw new Error("notFound() is not available in preview");
}
