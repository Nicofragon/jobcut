"use client";

import { useState } from "react";
import { Icon } from "./icons";

// Friendly chip input: type a value, press Enter (or comma) to add; click ✕ to remove.
// Used for roles, locations, skills, must-haves, dealbreakers — never raw text/JSON.
export default function TagInput({
  values,
  onChange,
  placeholder,
}: {
  values: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");

  function add(raw: string) {
    const v = raw.trim().replace(/,$/, "").trim();
    if (!v || values.includes(v)) return;
    onChange([...values, v]);
  }

  function onKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add(draft);
      setDraft("");
    } else if (e.key === "Backspace" && !draft && values.length) {
      onChange(values.slice(0, -1));
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface p-2 transition-colors focus-within:border-primary">
      {values.map((v) => (
        <span
          key={v}
          className="inline-flex items-center gap-1 rounded-full bg-surface-sunken px-2.5 py-1 text-sm text-on-surface"
        >
          {v}
          <button
            type="button"
            onClick={() => onChange(values.filter((x) => x !== v))}
            className="text-on-surface-faint hover:text-[color:var(--color-accent-red)]"
            aria-label={`Remove ${v}`}
          >
            <Icon name="x" size={14} />
          </button>
        </span>
      ))}
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKey}
        onBlur={() => {
          if (draft.trim()) {
            add(draft);
            setDraft("");
          }
        }}
        placeholder={values.length ? "" : placeholder}
        className="min-w-[180px] flex-1 border-none bg-transparent px-1 py-1 text-sm text-on-surface outline-none placeholder:text-on-surface-faint"
      />
    </div>
  );
}
