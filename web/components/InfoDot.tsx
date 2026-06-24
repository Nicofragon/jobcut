"use client";

// A small "?" affordance that reveals a plain-language definition on hover/focus.
// Keyboard-accessible (focus-within) and non-blocking (the bubble is pointer-events-none).
export function InfoDot({ text, align = "center" }: { text: string; align?: "center" | "left" | "right" }) {
  const pos =
    align === "left"
      ? "left-0"
      : align === "right"
        ? "right-0"
        : "left-1/2 -translate-x-1/2";
  return (
    <span className="group/info relative inline-flex align-middle">
      <button
        type="button"
        aria-label={text}
        onClick={(e) => e.stopPropagation()}
        className="grid h-4 w-4 place-items-center rounded-full border border-border text-[10px] font-bold leading-none text-on-surface-faint transition-colors hover:border-primary hover:text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
      >
        ?
      </button>
      <span
        role="tooltip"
        className={`pointer-events-none absolute top-full z-20 mt-1.5 w-56 rounded-lg border border-border bg-surface px-3 py-2 text-xs font-normal leading-relaxed text-on-surface-variant opacity-0 shadow-pop transition-opacity duration-150 group-hover/info:opacity-100 group-focus-within/info:opacity-100 ${pos}`}
      >
        {text}
      </span>
    </span>
  );
}
