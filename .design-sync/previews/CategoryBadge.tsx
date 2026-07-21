import { CategoryBadge } from "web";

// Pipeline-stage chips. Each known category maps to a tuned accent color; an
// unknown category falls back to neutral gray.
export function Pipeline() {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
      <CategoryBadge category="Saved" />
      <CategoryBadge category="Applied" />
      <CategoryBadge category="Screen" />
      <CategoryBadge category="Interview" />
      <CategoryBadge category="Offer" />
      <CategoryBadge category="Rejected" />
      <CategoryBadge category="No response" />
    </div>
  );
}
