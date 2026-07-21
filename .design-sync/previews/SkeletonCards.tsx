import { SkeletonCards } from "web";

// Loading placeholder that mirrors the Today grid of job cards while data loads.
export function Grid() {
  return (
    <div style={{ maxWidth: 720 }}>
      <SkeletonCards count={2} />
    </div>
  );
}
