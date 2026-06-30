"use client";

import { useState } from "react";
import { Icon } from "./icons";

type Theme = "light" | "dark";

// A lazy initializer reads localStorage — the same source the inline <head> script
// (layout.tsx) used to set data-theme before paint — so React's initial state always
// agrees with the DOM the script produced. The server has no localStorage and renders
// "light"; suppressHydrationWarning on the controls covers that one-frame icon swap.
function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(() => {
    if (typeof window === "undefined") return "light";
    try {
      return localStorage.getItem("theme") === "dark" ? "dark" : "light";
    } catch {
      return "light";
    }
  });

  function setTheme(next: Theme) {
    setThemeState(next);
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem("theme", next);
    } catch {
      /* private mode / storage disabled — the choice just won't persist */
    }
  }

  return [theme, setTheme];
}

// Compact icon button — for the nav. Shows the icon of the theme you'd switch TO.
export default function ThemeToggle({ className = "" }: { className?: string }) {
  const [theme, setTheme] = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      suppressHydrationWarning
      className={`grid h-8 w-8 place-items-center rounded-lg text-on-surface-variant transition-colors hover:bg-surface-alt hover:text-on-surface ${className}`}
    >
      <Icon name={theme === "dark" ? "sun" : "moon"} size={18} />
    </button>
  );
}

// Labelled Light / Dark segmented control — for the Settings "Appearance" card.
export function ThemeSegmented() {
  const [theme, setTheme] = useTheme();
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
            suppressHydrationWarning
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
