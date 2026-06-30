"use client";

import { useSyncExternalStore } from "react";
import { Icon } from "./icons";

type Theme = "light" | "dark";

// The inline <head> script (layout.tsx) sets data-theme from localStorage before
// paint, so the *page colors* are always correct on load. These controls, however,
// render theme-dependent markup (a sun/moon icon, an aria-pressed segment), and the
// server can't read localStorage — it always renders the "light" variant. If the
// client's first render disagreed (showing "dark"), React would hit a hydration
// mismatch on the nested <svg> (which a one-level suppressHydrationWarning does NOT
// cover), recover by re-rendering from the root, and in doing so discard the
// data-theme the script set — silently reverting the theme on every reload.
//
// useSyncExternalStore is the right tool: it serves the SERVER snapshot ("light")
// during hydration so the first client render matches the server, then re-renders
// with the real client value — a transition React explicitly supports without a
// hydration mismatch. localStorage is the single source of truth (same key the head
// script reads); a "storage" subscription keeps other tabs in sync for free.
const listeners = new Set<() => void>();

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  window.addEventListener("storage", onChange);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

function getSnapshot(): Theme {
  try {
    return localStorage.getItem("theme") === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

// Server (and the first, hydration-matching client render) has no localStorage.
function getServerSnapshot(): Theme {
  return "light";
}

function setTheme(next: Theme) {
  document.documentElement.setAttribute("data-theme", next);
  try {
    localStorage.setItem("theme", next);
  } catch {
    /* private mode / storage disabled — the choice just won't persist */
  }
  // "storage" doesn't fire in the tab that wrote it, so notify our own subscribers.
  listeners.forEach((l) => l());
}

function useTheme(): Theme {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

// Compact icon button — for the nav. Shows the icon of the theme you'd switch TO.
export default function ThemeToggle({ className = "" }: { className?: string }) {
  const theme = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      className={`grid h-8 w-8 place-items-center rounded-lg text-on-surface-variant transition-colors hover:bg-surface-alt hover:text-on-surface ${className}`}
    >
      <Icon name={theme === "dark" ? "sun" : "moon"} size={18} />
    </button>
  );
}

// Labelled Light / Dark segmented control — for the Settings "Appearance" card.
export function ThemeSegmented() {
  const theme = useTheme();
  const options: { id: Theme; label: string; icon: "sun" | "moon" }[] = [
    { id: "light", label: "Light", icon: "sun" },
    { id: "dark", label: "Dark", icon: "moon" },
  ];
  return (
    <div className="inline-flex gap-1 rounded-lg border border-border bg-surface-alt p-1" role="group" aria-label="Theme">
      {options.map((o) => {
        const selected = theme === o.id;
        return (
          <button
            key={o.id}
            type="button"
            onClick={() => setTheme(o.id)}
            aria-pressed={selected}
            className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              selected
                ? "bg-surface text-on-surface shadow-card"
                : "text-on-surface-variant hover:text-on-surface"
            }`}
          >
            <Icon name={o.icon} size={16} /> {o.label}
          </button>
        );
      })}
    </div>
  );
}
