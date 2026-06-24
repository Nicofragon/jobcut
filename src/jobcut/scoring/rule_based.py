"""rule_based — the DEFAULT scorer. Pure Python, no API key, no cost.

This is the floor: the repo must work for someone who never touches an LLM. The
rubric is transparent and tunable via config/config.json → "scoring.weights":

  +title       title matches a target role (config "filter.include_titles")
  +stack       stack keywords present (from taxonomy.json skills); half if only 1
  +location    workable location (home full, region-remote partial)
  +signals     profile "nice-to-have" signals present (config "scoring.signals")
  +employer    reasonable employer (named company, plausible size)
  +reachable   few applicants (<50) or a named recruiter
  +dealbreaker (negative) a hard requirement you don't meet (config "scoring.dealbreakers")
  out-of-profile titles (any title that doesn't match your target roles) capped low

ROLE-AGNOSTIC: nothing here is wired to a specific field. title/stack/signals/
dealbreakers all come from the user's profile-derived config + taxonomy, so the
same rubric works for a nurse, a marketer or a data analyst.
"""

from __future__ import annotations

import re

from ..route import geo
from .base import JobScore, Scorer

_NUM = re.compile(r"\d[\d,\.]*")
_DEFAULT_DEALBREAKERS = [r"security clearance", r"\bclearance required\b"]


def _max_num(s) -> int | None:
    nums = [int(m.group(0).replace(",", "").replace(".", "")) for m in _NUM.finditer(str(s))]
    return max(nums) if nums else None


class RuleBasedScorer(Scorer):
    def __init__(self, taxonomy=None, weights=None, include_titles=None,
                 out_of_profile_cap=30, dealbreakers=None, signals=None):
        self.weights = weights or {}
        self.cap = out_of_profile_cap
        self.include = re.compile(include_titles, re.I) if include_titles else None
        self.skill_pats = []
        for spec in (taxonomy or {}).get("skills", {}).values():
            self.skill_pats += [re.compile(p, re.I) for p in spec.get("patterns", [])]
        # profile-derived "nice-to-have" boost signals (no field-specific defaults)
        self.signal_pats = [re.compile(p, re.I) for p in (signals or [])]
        self.dealbreakers = [re.compile(p, re.I) for p in (dealbreakers or _DEFAULT_DEALBREAKERS)]

    # --- component helpers ---
    def _reasonable_employer(self, job) -> bool:
        if not str(job.get("company_name", "")).strip():
            return False
        size = _max_num(job.get("company_size", ""))
        return size is None or size >= 20   # unknown size with a named company gets the benefit

    def _reachable(self, job) -> bool:
        if str(job.get("recruiter_name", "")).strip():
            return True
        applicants = _max_num(job.get("applicants", ""))
        return applicants is not None and applicants < 50

    def score(self, job: dict, profile: str = "") -> JobScore:
        w = self.weights
        title = str(job.get("title", ""))
        text = (title + " " + str(job.get("description", ""))).lower()
        reasons, score = [], 0

        title_match = bool(self.include and self.include.search(title))
        if title_match:
            score += w.get("title", 30); reasons.append("title match")

        n_skills = sum(1 for p in self.skill_pats if p.search(text))
        if n_skills >= 1:
            pts = w.get("stack", 20) if n_skills >= 2 else round(w.get("stack", 20) / 2)
            score += pts; reasons.append(f"{n_skills} stack skill(s)")

        g = geo(job.get("location", ""))
        if g == "home":
            score += w.get("location", 15); reasons.append("home location")
        elif g == "region":
            score += round(w.get("location", 15) * 0.7); reasons.append("region (remote)")

        if self.signal_pats and any(p.search(text) for p in self.signal_pats):
            score += w.get("signals", w.get("ai", 10)); reasons.append("profile signals")
        if self._reasonable_employer(job):
            score += w.get("employer", 10); reasons.append("reasonable employer")
        if self._reachable(job):
            score += w.get("reachable", 10); reasons.append("reachable")
        if any(p.search(text) for p in self.dealbreakers):
            score += w.get("dealbreaker", -20); reasons.append("dealbreaker")

        # Out of profile = the title doesn't match any target role (role-agnostic; no
        # hardcoded role list). Pipeline pre-discards these, so this is a safety net.
        if not title_match:
            score = min(score, self.cap); reasons.append("out-of-profile title")

        score = max(0, min(100, score))
        return JobScore(
            job_id=str(job.get("job_id", "")),
            match_score=int(score),
            match_reasons=", ".join(reasons)[:160] or "no strong signals",
            status="scored",
        )
