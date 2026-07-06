# jobcut web console

The Next.js front-end for [jobcut](../README.md) — the local job-search tracker. It's a
static export (`next build` → `web/out/`) that the jobcut API serves as a single process;
you don't deploy it anywhere.

## You don't run this directly

For normal use, start everything with one command from the repo root:

```bash
jobcut serve --open      # builds the console if needed, serves API + UI, opens the browser
```

That serves the built console and the API together at `http://127.0.0.1:8000`. See the
[root README](../README.md) and the [user manual](../docs/MANUAL.md) for the full workflow.

## Developing the console

Work on the UI with the Next.js dev server (hot reload), pointed at a running API:

```bash
# terminal 1 — the API (and, incidentally, the built console) on :8000
jobcut serve

# terminal 2 — the dev server on :3000, proxying API calls to :8000
cd web
npm install
npm run dev
```

Open `http://localhost:3000`. The dev server talks to the API on `:8000` (CORS is allowed
for `localhost:3000`).

Before opening a PR, keep it green:

```bash
npm run lint
npm run build     # must succeed — `jobcut serve` ships whatever this produces in web/out/
```

## Notes

- **This is not stock Next.js** — read [`AGENTS.md`](AGENTS.md) before changing framework
  code; some APIs and conventions differ from what you may expect.
- The build output (`web/out/`) and `node_modules/` are git-ignored; the API serves
  `web/out/` when it exists and falls back to API-only when it doesn't.
