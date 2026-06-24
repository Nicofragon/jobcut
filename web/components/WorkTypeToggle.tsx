"use client";

// Multi-select segmented control for work types. Values match the Apify actor's
// workplaceType enum (remote / hybrid / office); "On-site" is just the label.
const WORK_TYPES = [
  { value: "remote", label: "Remote" },
  { value: "hybrid", label: "Hybrid" },
  { value: "office", label: "On-site" },
];

export default function WorkTypeToggle({
  values,
  onChange,
}: {
  values: string[];
  onChange: (v: string[]) => void;
}) {
  return (
    <div className="inline-flex w-full gap-1 rounded-lg bg-surface-sunken p-1 md:w-auto">
      {WORK_TYPES.map((wt) => {
        const on = values.includes(wt.value);
        return (
          <button
            key={wt.value}
            type="button"
            onClick={() => onChange(on ? values.filter((v) => v !== wt.value) : [...values, wt.value])}
            className={`flex-1 rounded-md px-5 py-1.5 text-sm font-medium transition-all md:flex-none ${
              on ? "bg-surface text-on-surface shadow-card" : "text-on-surface-variant hover:bg-surface-alt"
            }`}
          >
            {wt.label}
          </button>
        );
      })}
    </div>
  );
}
