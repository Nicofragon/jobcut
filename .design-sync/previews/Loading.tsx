import { Loading } from "web";

// Centered inline loading state with the spinner + a caption. Default caption.
export function Default() {
  return <Loading />;
}

// A task-specific caption.
export function Scoring() {
  return <Loading label="Scoring jobs against your profile…" />;
}
