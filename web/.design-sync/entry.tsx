// design-sync barrel entry — re-exports every scoped console component under a
// single module so esbuild can assign them all to window.JobcutDs.*.
// Default-export components are re-named here (a synth `export *` entry would
// silently drop them). Kept in sync with .design-sync/config.json componentSrcMap.
// Hand-written, committed; contains no data/secrets/paths.
import "./shim"; // load-first: defines globalThis.process for standalone render
export { default as JobCard } from "../components/JobCard";
export { default as Logo } from "../components/Logo";
export { default as Nav } from "../components/Nav";
export { default as RunControls } from "../components/RunControls";
export { default as ScoreRing } from "../components/ScoreRing";
export { default as StatusSelect } from "../components/StatusSelect";
export { default as TagInput } from "../components/TagInput";
export { default as WorkTypeToggle } from "../components/WorkTypeToggle";
export { ScoreBadge, CategoryBadge } from "../components/Badges";
export { Spinner, Loading, ErrorNote, SkeletonCards, SkeletonRows } from "../components/States";
export { Icon } from "../components/icons";
export { InfoDot } from "../components/InfoDot";
