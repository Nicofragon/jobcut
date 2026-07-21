import { JobCard } from "web";

// A scored shortlist offer as it appears on the Today screen: title + company,
// match ring, workplace/location chips, freshness, "why it matches", and the
// status control. The whole card is a link to the detail view.
const base = {
  job_id: "li-8842",
  title: "Senior Frontend Engineer",
  company_name: "Mercado Libre",
  location: "Buenos Aires, Argentina",
  score: 88,
  match_reasons:
    "Strong React + TypeScript match and remote-first. Fintech domain overlaps your Preply and payments work; salary band aligns with your target.",
  linkedin_url: "https://www.linkedin.com/jobs/view/8842",
  apply_url: null,
  easy_apply_url: null,
  scored_date: "2026-07-20",
  workplace_type: "remote",
  status: "applied",
  backend: "claude_skills",
  first_seen: "2026-07-20",
  posted_date: "2026-07-18",
};

// The canonical, high-match card.
export function Default() {
  return (
    <div style={{ maxWidth: 460 }}>
      <JobCard item={base} />
    </div>
  );
}

// A mid-score, hybrid role that hasn't been actioned yet — different chips,
// score color, and a rule-based backend label.
export function MidMatch() {
  return (
    <div style={{ maxWidth: 460 }}>
      <JobCard
        item={{
          ...base,
          job_id: "li-9110",
          title: "Product Designer",
          company_name: "Globant",
          location: "Remote — LATAM",
          score: 64,
          workplace_type: "hybrid",
          status: null,
          backend: "rule_based",
          match_reasons:
            "Design-systems experience is a fit; role leans more visual than your recent front-end focus. Comp not disclosed.",
          posted_date: "2026-07-15",
          first_seen: "2026-07-16",
        }}
      />
    </div>
  );
}
