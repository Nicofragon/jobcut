# jobcut Design System — how to build with it

A small, opinionated set for the **jobcut** job-search console: a Next.js + Tailwind v4
app. Components are the real shipped console primitives; build new UI by composing them
and by writing layout with the **same Tailwind token utilities** they use.

## Setup & theming — no provider needed

Components are self-contained (no context/provider wrapper). All styling comes from the
design system's stylesheet; just make sure it's loaded. Theming is **token-based**:

- Light is the default. **Dark mode** = set `data-theme="dark"` on a root element
  (e.g. `<html data-theme="dark">`); every token flips, no per-component change.
- The type family is **Inter** (`--font-inter`), applied via `--font-sans` on `body`.

## Styling idiom — Tailwind utilities bound to theme tokens

Do NOT hardcode hex colors or `gray-500`-style palette classes. Style with these
token utilities (each maps to a `--color-*` / radius / shadow CSS variable):

| Purpose | Classes |
|---|---|
| Surfaces | `bg-bg` (page), `bg-surface` (cards), `bg-surface-alt`, `bg-surface-sunken` |
| Text | `text-on-surface` (primary), `text-on-surface-variant` (secondary), `text-on-surface-faint` (hint) |
| Brand / actions | `bg-primary`, `text-on-primary`, `hover:bg-primary-hover`, `text-primary`, `text-primary-strong`, `bg-primary-tint` |
| Borders | `border-border` |
| Status accents | `text-accent-red` (utility); the rest via token: `text-[color:var(--color-accent-blue)]` — also `--color-accent-{amber,purple,cyan}` |
| Radius | `rounded-card` (14px, cards/panels), `rounded-lg` (8px, buttons/inputs), `rounded-full` |
| Elevation | `shadow-card` (resting), `shadow-pop` (raised/overlays) |

Match-score color (green ≥75 / amber ≥50 / gray) is encoded by `ScoreRing` / `ScoreBadge`
themselves — pass a `score`, don't recolor them.

## Components (`window.JobcutDs.*`)

Cards/data: `JobCard` (a scored offer — pass a `ShortlistItem`), `ScoreRing`, `ScoreBadge`,
`CategoryBadge`, `StatusSelect`. Inputs: `TagInput`, `WorkTypeToggle`. Chrome: `Nav`,
`Logo`, `Icon` (local SVG set, pass `name`), `RunControls`, `InfoDot`. States: `Loading`,
`Spinner`, `ErrorNote`, `SkeletonCards`, `SkeletonRows`. Read each component's
`.d.ts` for its exact props and `.prompt.md` for usage.

## Where the truth lives

- **Styling source**: the design system's `styles.css` and its `@import` closure (the
  compiled Tailwind stylesheet — the full token + utility set) plus the per-component
  `_preview` cards.
- **Per component**: `components/general/<Name>/<Name>.d.ts` (API) and `.prompt.md` (usage).

## One idiomatic snippet

```tsx
// A summary panel composed from library parts + token-utility layout glue.
<section className="rounded-card border border-border bg-surface p-6 shadow-card">
  <div className="flex items-center justify-between">
    <h2 className="text-lg font-semibold text-on-surface">Top match today</h2>
    <ScoreRing score={88} size={48} />
  </div>
  <p className="mt-1 text-sm text-on-surface-variant">Senior Frontend Engineer · Mercado Libre</p>
  <div className="mt-4 flex items-center gap-3">
    <CategoryBadge category="Interview" />
    <button className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-on-primary hover:bg-primary-hover">
      View details
    </button>
  </div>
</section>
```
