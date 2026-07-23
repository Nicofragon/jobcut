import { RunControls } from "web";

// The Today-screen action bar: "Re-score" (free, re-evaluates existing jobs) and
// "Find new jobs" (runs saved searches via Apify, behind a cost confirmation).
export function Default() {
  return <RunControls />;
}
