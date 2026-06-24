import { defineConfig, devices } from "@playwright/test";

// E2E smoke for the core loop. Playwright boots the stack itself:
//   - the API (uvicorn) on :8000, with a scratch data dir at repo root
//   - the Next dev server on :3000
// reuseExistingServer means it attaches to a stack you already have running.
//
// First time only:  npx playwright install chromium
// Then:             npm run e2e
//
// The nav smoke runs against an empty DB; to exercise the full loop test, seed
// the scratch dir first:  JOBCUT_DATA_DIR=$(pwd)/.e2e-data jobcut init
// --no-input && python scripts/seed_demo.py && jobcut score
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
  },
  webServer: [
    {
      command: "python -m uvicorn jobcut.api.app:app --port 8000",
      cwd: "..",
      url: "http://localhost:8000/api/status",
      reuseExistingServer: true,
      timeout: 60_000,
      // relative to cwd (repo root) → resolved by paths.data_dir()
      env: { JOBCUT_DATA_DIR: ".e2e-data" },
    },
    {
      command: "npm run dev",
      url: "http://localhost:3000",
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
