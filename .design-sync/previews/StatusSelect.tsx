import { StatusSelect } from "web";

// Application-status selector: a status-colored icon beside a pill dropdown.
// Shown across a few pipeline stages.
export function Stages() {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 16 }}>
      <StatusSelect jobId="li-1" value="applied" />
      <StatusSelect jobId="li-2" value="screen" />
      <StatusSelect jobId="li-3" value="interview" />
      <StatusSelect jobId="li-4" value="offer" />
    </div>
  );
}

// The unset state, prompting the user to choose.
export function Unset() {
  return <StatusSelect jobId="li-5" value={null} />;
}
