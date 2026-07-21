import { useState } from "react";
import { WorkTypeToggle } from "web";

// Multi-select segmented control for workplace types (remote / hybrid / on-site).
// Selected segments lift onto a white surface with a soft shadow.
export function Selected() {
  const [values, setValues] = useState<string[]>(["remote", "hybrid"]);
  return (
    <div style={{ maxWidth: 360 }}>
      <WorkTypeToggle values={values} onChange={setValues} />
    </div>
  );
}

// Nothing selected — the neutral resting state.
export function None() {
  const [values, setValues] = useState<string[]>([]);
  return (
    <div style={{ maxWidth: 360 }}>
      <WorkTypeToggle values={values} onChange={setValues} />
    </div>
  );
}
