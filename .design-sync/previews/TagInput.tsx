import { useState } from "react";
import { TagInput } from "web";

// Chip input for roles, locations, skills, must-haves and dealbreakers. Type
// and press Enter (or comma) to add a chip; click ✕ to remove one. Stateful so
// the preview is actually interactive.
export function Skills() {
  const [values, setValues] = useState<string[]>([
    "Senior Frontend",
    "React",
    "TypeScript",
    "Remote",
  ]);
  return (
    <div style={{ maxWidth: 460 }}>
      <TagInput values={values} onChange={setValues} placeholder="Add a skill…" />
    </div>
  );
}

// The empty state, showing the placeholder.
export function Empty() {
  const [values, setValues] = useState<string[]>([]);
  return (
    <div style={{ maxWidth: 460 }}>
      <TagInput values={values} onChange={setValues} placeholder="Add a location…" />
    </div>
  );
}
