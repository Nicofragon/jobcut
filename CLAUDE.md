# jobcut — working agreement (fluid solo-dev workflow)

This is a solo-dev, pre-release repo. Work **fluidly**: don't stop between
sub-steps, and don't open a branch per block.

## Workflow

- **Work directly on `main`.** No per-block feature branches.
- **Per block:** implement (TDD where there are tests) → get build/test/lint
  green → make one clear commit → `git push origin main`. Don't pause between
  sub-steps; carry the block to "pushed" on your own.
- Give a **single summary at the end of the block**, not running commentary.

## When to STOP and ask

Stop only when:
- you need a **real design/product decision** (not a default you can pick),
- **tests fail and you can't fix them**, or
- the work falls **outside the scope** that was asked for.

## Guardrails (don't cross without flagging first)

- Don't change **API or DB contracts** without saying so up front.
- **Never** force-push or rewrite already-pushed history.
- Stop before **deleting data** or **installing heavy dependencies**.

## Verification commands

- Backend: `.venv/bin/python -m pytest -q` and `.venv/bin/ruff check src/ tests/`
- Web: `cd web && npm run build && npm run lint`

## Tracked vs not

- Commit code, tests, and the user-facing docs (`README.md`, `docs/MANUAL.md`,
  `docs/WORKFLOW.md`). Keep architecture/strategy docs and design assets out of the
  public repo.
- Leave untracked: `.claude/`, `.playwright-mcp/`, `bin/`, `scripts/` (local-only).
