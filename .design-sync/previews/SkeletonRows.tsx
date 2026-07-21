import { SkeletonRows } from "web";

// Loading placeholder for the Applications list (row-per-application layout).
export function Rows() {
  return (
    <div style={{ maxWidth: 560 }}>
      <SkeletonRows count={4} />
    </div>
  );
}
