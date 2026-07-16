"""profile.py — parse profile.md and DERIVE the targeting (searches + rubric).

The role-agnostic floor (no AI): the user's profile.md is the single source of
truth, and this module turns its stable headings into the artifacts the pipeline
already consumes — searches/*.json, config.json (include_titles, routing,
scoring signals/dealbreakers) and taxonomy.json (skills, role_segments).

Nothing here is hardcoded to any role: a nurse's profile yields nurse searches
and a nurse rubric. The optional AI layer (CV → profile, suggestions) plugs in
later (§8.5); this is the deterministic fallback that always works.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from . import config, paths


@dataclass
class Skill:
    """One profile skill: your standing on it, plus how it's bucketed in the kit.

    `status` is the have/partial/gap trichotomy the taxonomy + Discovery already use;
    `category` groups it (core/viz/dataeng/…); `aliases` add extra match patterns.
    """
    name: str
    status: str = "have"        # have | partial | gap
    category: str = "core"
    aliases: list[str] = field(default_factory=list)


@dataclass
class ProfileData:
    target_titles: list[str] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)     # canonical (status-aware)
    based_in: str = ""
    remote_mode: str = ""
    dealbreakers: list[str] = field(default_factory=list)
    notes: str = ""

    # Back-compat flat views (older callers/tests read these). Derived from `skills`.
    @property
    def core_skills(self) -> list[str]:
        return [s.name for s in self.skills if s.status == "have"]

    @property
    def nice_skills(self) -> list[str]:
        return [s.name for s in self.skills if s.status == "partial"]

    @property
    def gap_skills(self) -> list[str]:
        return [s.name for s in self.skills if s.status == "gap"]


# --- parsing ----------------------------------------------------------------

def _sections(md: str) -> dict[str, str]:
    """Split markdown into {heading_lower: body} by ATX (`#`) headings."""
    sections: dict[str, str] = {}
    cur, buf = None, []
    for line in (md or "").splitlines():
        h = re.match(r"#{1,6}\s+(.*)", line)
        if h:
            if cur is not None:
                sections[cur] = "\n".join(buf)
            cur, buf = h.group(1).strip().lower(), []
        else:
            buf.append(line)
    if cur is not None:
        sections[cur] = "\n".join(buf)
    return sections


def _find(sections: dict[str, str], *needles: str) -> str:
    for h, body in sections.items():
        if any(n in h for n in needles):
            return body
    return ""


def _bullets(text: str) -> list[str]:
    """Bullet items under a section, dropping help/placeholder lines."""
    out = []
    for line in text.splitlines():
        m = re.match(r"[-*]\s+(.*)", line.strip())
        if not m:
            continue
        item = m.group(1).strip()
        if not item or re.fullmatch(r"\(.*\)", item):   # e.g. "(add yours)"
            continue
        out.append(item)
    return out


def _line_value(text: str, key: str) -> str:
    for line in text.splitlines():
        if key in line.lower() and ":" in line:
            return line.split(":", 1)[1].strip()
    return ""


# profile.md skill sections → status. Back-compatible: old profiles have only the first
# two; "Skill gaps" is the new section that lets the profile carry `gap` skills.
_STATUS_SECTIONS = [(("core skill",), "have"), (("nice", "learning"), "partial"), (("skill gap",), "gap")]


def _skills_from(secs: dict[str, str]) -> list[Skill]:
    """Build the status-aware skill list from the three skill sections (first wins on dup)."""
    out, seen = [], set()
    for needles, status in _STATUS_SECTIONS:
        for item in _bullets(_find(secs, *needles)):
            key = _skill_name(item).lower()
            if key and key not in seen:
                seen.add(key)
                out.append(Skill(name=item, status=status))   # name keeps the raw bullet (annotations)
    return out


def parse(md: str) -> ProfileData:
    """Parse profile.md into structured fields (tolerant: missing sections -> empty)."""
    secs = _sections(md)
    loc = _find(secs, "location", "work mode")
    return ProfileData(
        target_titles=_bullets(_find(secs, "target role", "target title")),
        skills=_skills_from(secs),
        based_in=_line_value(loc, "based in"),
        remote_mode=_line_value(loc, "remote"),
        dealbreakers=_bullets(_find(secs, "dealbreaker")),
        notes=_find(secs, "notes").strip(),
    )


def load() -> ProfileData:
    """Parse the profile.md in the data dir (empty ProfileData if absent)."""
    p = paths.data_dir() / "profile.md"
    return parse(p.read_text() if p.exists() else "")


# --- structured layer (B1) --------------------------------------------------
# A form-friendly view that round-trips with the canonical headings `parse()`
# reads. profile.md stays the source of truth; this just (de)serializes it.

class ProfileFields(BaseModel):
    """Structured profile for the friendly form. Round-trips with profile.md headings."""

    target_roles: list[str] = Field(default_factory=list)   # "Target roles"
    locations: list[str] = Field(default_factory=list)      # "Location & work mode" → Based in
    work_types: list[str] = Field(default_factory=list)     # "Location & work mode" → Remote
    seniority: str | None = None                            # "Seniority" (optional)
    must_haves: list[str] = Field(default_factory=list)     # "Nice-to-have / learning" (partial)
    dealbreakers: list[str] = Field(default_factory=list)   # "Dealbreakers"
    skills: list[str] = Field(default_factory=list)         # "Core skills" (have)
    gaps: list[str] = Field(default_factory=list)           # "Skill gaps" (gap — learning targets)


# headings whose bodies `from_structured` regenerates (everything else is preserved)
_MANAGED_NEEDLES = [
    ("target role", "target title"), ("seniority",), ("core skill",),
    ("nice", "learning"), ("skill gap",), ("location", "work mode"), ("dealbreaker",),
]


def _is_managed(heading_lower: str) -> bool:
    return any(any(n in heading_lower for n in grp) for grp in _MANAGED_NEEDLES)


def _iter_headings(md: str):
    """Yield (level, heading_text, body) for each ATX section in order (skips preamble)."""
    level = head = None
    buf: list[str] = []
    for line in (md or "").splitlines():
        m = re.match(r"(#{1,6})\s+(.*)", line)
        if m:
            if head is not None:
                yield level, head, "\n".join(buf)
            level, head, buf = len(m.group(1)), m.group(2).strip(), []
        else:
            buf.append(line)
    if head is not None:
        yield level, head, "\n".join(buf)


def _csv(items: list[str]) -> str:
    return ", ".join(i.strip() for i in items if i.strip())


def _split_csv(value: str) -> list[str]:
    return [p.strip() for p in (value or "").split(",") if p.strip()]


def to_structured(md: str) -> ProfileFields:
    """Parse profile.md into ProfileFields (reuses parse(); seniority read separately)."""
    pd = parse(md)
    seniority = _find(_sections(md), "seniority").strip()
    return ProfileFields(
        target_roles=pd.target_titles,
        locations=_split_csv(pd.based_in),
        work_types=_split_csv(pd.remote_mode),
        seniority=seniority or None,
        must_haves=pd.nice_skills,
        dealbreakers=pd.dealbreakers,
        skills=pd.core_skills,
        gaps=pd.gap_skills,
    )


def _bullets_md(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items)


def from_structured(fields: ProfileFields, base_md: str = "") -> str:
    """Serialize ProfileFields to canonical headings parse() understands.

    Non-destructive where it can be: sections it does not model (e.g. "Notes for
    the scorer", custom headings) are carried over verbatim from `base_md`.
    """
    parts = ["# My profile", "", "## Target roles", "", _bullets_md(fields.target_roles)]
    if fields.seniority:
        parts += ["", "## Seniority", "", fields.seniority]
    parts += ["", "## Core skills", "", _bullets_md(fields.skills)]
    parts += ["", "## Nice-to-have / learning", "", _bullets_md(fields.must_haves)]
    if fields.gaps:
        parts += ["", "## Skill gaps", "", _bullets_md(fields.gaps)]
    parts += ["", "## Location & work mode", "",
              f"- Based in: {_csv(fields.locations)}", f"- Remote: {_csv(fields.work_types)}"]
    parts += ["", "## Dealbreakers", "", _bullets_md(fields.dealbreakers)]

    for level, heading, body in _iter_headings(base_md):
        if level == 1 or _is_managed(heading.lower()):
            continue                              # title + managed sections are regenerated above
        block = body.strip("\n")
        parts += ["", f"{'#' * level} {heading}"] + (["", block] if block else [])

    return "\n".join(parts).rstrip() + "\n"


# --- derivation helpers -----------------------------------------------------

_SENIORITY = re.compile(r"\b(senior|junior|lead|staff|principal|sr|jr|mid|entry|head of|chief)\b", re.I)
_DEALBREAKER_STOP = {
    "fluent", "required", "require", "speak", "hold", "take", "work", "with", "you", "your",
    "dont", "don't", "languages", "language", "active", "must", "have", "need", "that", "this",
    "location", "role", "domains", "domain", "they",
}


def _title_phrase(t: str) -> str:
    t = _SENIORITY.sub("", t.lower())
    t = re.sub(r"[^\w\s/&+-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _slug(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


def _skill_name(s: str) -> str:
    return re.sub(r"\s*\(.*\)\s*$", "", s).strip()   # drop trailing "(pandas, numpy)"


def _skill_pattern(s: str) -> str:
    n = _skill_name(s).lower()
    esc = re.escape(n)
    return rf"\b{esc}\b" if re.fullmatch(r"[\w ]+", n) else esc


def _dealbreaker_pattern(b: str) -> str | None:
    """Best-effort: the most distinctive content word becomes a loose pattern."""
    words = [w for w in re.findall(r"[a-záéíóúñ]+", b.lower())
             if len(w) >= 4 and w not in _DEALBREAKER_STOP]
    if not words:
        return None
    return rf"\b{re.escape(max(words, key=len))}\b"


# --- derivation -------------------------------------------------------------

def derive_include_titles(pd: ProfileData) -> str | None:
    phrases = sorted({p for p in (_title_phrase(t) for t in pd.target_titles) if p})
    return "(" + "|".join(re.escape(p) for p in phrases) + ")" if phrases else None


def derive_routing(pd: ProfileData) -> tuple[str | None, str | None]:
    if not pd.based_in:
        return None, None
    toks = [re.sub(r"[^\w\s]", "", t).strip().lower() for t in re.split(r"[,/]", pd.based_in)]
    toks = list(dict.fromkeys(t for t in toks if t))
    if not toks:
        return None, None
    home = r"\b(" + "|".join(re.escape(t) for t in toks) + r")\b"
    region = r"\b(" + re.escape(toks[-1]) + r")\b"   # broadest token = country
    return home, region


# default "how to close it" per status (user overrides survive re-derive via merge_taxonomy)
_CLOSE_VIA_DEFAULT = {"partial": "cv-reframe", "gap": "course"}


def derive_taxonomy(pd: ProfileData) -> dict:
    """The kit from the profile: every skill with its status/category/close_via/patterns.

    Unlike the old core-only/all-"have" version, this emits partial + gap skills too (what
    Discovery's coverage/gaps need) and a `close_via` for non-have skills.
    """
    skills = {}
    for s in pd.skills:
        name = _skill_name(s.name)
        if not name:
            continue
        patterns = [_skill_pattern(s.name)] + [_skill_pattern(a) for a in s.aliases if _skill_name(a)]
        entry = {"cat": s.category or "core", "status": s.status,
                 "patterns": list(dict.fromkeys(patterns))}
        if s.status in _CLOSE_VIA_DEFAULT:
            entry["close_via"] = _CLOSE_VIA_DEFAULT[s.status]
        skills[name] = entry
    segments = {}
    for t in pd.target_titles:
        ph = _title_phrase(t)
        if ph:
            segments.setdefault(_slug(t) or "target", []).append(ph)
    return {"skills": skills, "role_segments": segments}


def derive_config(pd: ProfileData) -> dict:
    cfg: dict = {"filter": {}, "routing": {}, "scoring": {}}
    inc = derive_include_titles(pd)
    if inc:
        cfg["filter"]["include_titles"] = inc
    home, region = derive_routing(pd)
    if home:
        cfg["routing"]["home"] = home
    if region:
        cfg["routing"]["region"] = region
    signals = [_skill_pattern(s) for s in pd.nice_skills if _skill_name(s)]
    if signals:
        cfg["scoring"]["signals"] = signals
    deal = [p for p in (_dealbreaker_pattern(b) for b in pd.dealbreakers) if p]
    if deal:
        cfg["scoring"]["dealbreakers"] = deal
    return {k: v for k, v in cfg.items() if v}


def _search_note(pd: ProfileData) -> str:
    return (f"Generated from profile (based in: {pd.based_in or 'unset'}). "
            "Edit `locations` to your city/country (LinkedIn understands plain names). "
            "A geoId is optional precision. Remote hireability is decided by route.py.")


def derive_searches(pd: ProfileData) -> dict[str, dict]:
    if not pd.target_titles:
        return {}
    # The actor takes free-text `locations`; use the profile's base location so a new
    # user gets a runnable search with no geoId to hunt down (geoId stays optional).
    base = {"jobTitles": pd.target_titles,
            "employmentType": ["full-time"], "postedLimit": "24h", "sortBy": "relevance"}
    if pd.based_in:
        base["locations"] = [pd.based_in]
    note = _search_note(pd)
    rm = pd.remote_mode.lower()
    slug = _slug(pd.based_in) or "local"
    searches: dict[str, dict] = {}

    # NB: the actor's allowed workplaceType values are "remote" | "hybrid" | "office"
    # (it has no "on-site" — that label maps to "office").
    if "on-site only" in rm or "onsite only" in rm:
        searches[slug] = {**base, "workplaceType": ["office"], "maxItems": 50, "_note": note}
    elif "hybrid only" in rm:
        searches[slug] = {**base, "workplaceType": ["hybrid", "office"], "maxItems": 50, "_note": note}
    else:
        searches[slug] = {**base, "workplaceType": ["office", "hybrid"], "maxItems": 50, "_note": note}
        if "yes" in rm or "remote" in rm:
            searches["remote"] = {**base, "workplaceType": ["remote"], "maxItems": 65,
                                  "_note": "Remote search. Widen `locations` to your region/country; route.py decides hireability."}
    return searches


# --- merge (preserve manual edits) ------------------------------------------

def _read_json(p) -> dict:
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except (ValueError, OSError):
        return {}


def _union(*lists) -> list:
    out: list = []
    for lst in lists:
        for x in (lst or []):
            if x not in out:
                out.append(x)
    return out


def merge_taxonomy(derived: dict, existing: dict) -> dict:
    """Upsert the profile's skills onto the existing kit, preserving manual edits.

    The profile OWNS each skill's `status`; the existing `category`, hand-added `patterns`,
    and `close_via` are preserved (patterns unioned). Existing skills the profile doesn't
    mention are KEPT — removal stays a manual taxonomy edit in v1. `role_segments` are unioned.
    """
    ex_skills = (existing or {}).get("skills", {})
    out = {k: dict(v) for k, v in ex_skills.items()}
    for name, d in (derived or {}).get("skills", {}).items():
        cur = dict(ex_skills.get(name, {}))
        status = d["status"]                                   # profile owns status
        entry = {"cat": cur.get("cat") or d.get("cat", "core"),
                 "status": status,
                 "patterns": _union(cur.get("patterns", []), d.get("patterns", []))}
        if status in ("partial", "gap"):
            entry["close_via"] = cur.get("close_via") or d.get("close_via", "")
        out[name] = entry
    ex_seg = (existing or {}).get("role_segments", {})
    seg = {k: list(v) for k, v in ex_seg.items()}
    for name, phrases in (derived or {}).get("role_segments", {}).items():
        seg[name] = _union(ex_seg.get(name, []), phrases)
    return {"skills": out, "role_segments": seg}


def merge_config(derived: dict, existing: dict) -> dict:
    """Deep-merge derived config over existing, section by section, so hand-set keys
    (e.g. `scoring.weights`, `scoring.backend`) survive while derived keys refresh."""
    out = json.loads(json.dumps(existing or {}))
    for section, vals in (derived or {}).items():
        node = out.get(section)
        if isinstance(node, dict) and isinstance(vals, dict):
            node.update(vals)
        else:
            out[section] = vals
    return out


def _write(p, content: str, force: bool, report: dict) -> None:
    if p.exists() and not force:
        report["skipped"].append(str(p))
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    report["written"].append(str(p))


def apply(pd: ProfileData | None = None, *, force: bool = False,
          targets: list[str] | None = None) -> dict:
    """Write derived artifacts. MERGE by default (preserve manual edits); `force` overwrites.

    - searches: skipped if the file exists (unless `force`) — a tuned search is never clobbered.
    - config / taxonomy: merged with the existing file so hand-edits survive; `force` regenerates.
    """
    pd = pd if pd is not None else load()
    targets = targets or ["searches", "config", "taxonomy"]
    report: dict = {"written": [], "skipped": []}

    if "searches" in targets:
        for name, inp in derive_searches(pd).items():
            _write(paths.searches_dir() / f"{name}.json", json.dumps(inp, indent=2), force, report)
    if "config" in targets:
        derived = derive_config(pd)
        merged = derived if force else merge_config(derived, _read_json(config.config_file()))
        _write(config.config_file(), json.dumps(merged, indent=2), True, report)
    if "taxonomy" in targets:
        derived = derive_taxonomy(pd)
        merged = derived if force else merge_taxonomy(derived, _read_json(config.taxonomy_file()))
        _write(config.taxonomy_file(), json.dumps(merged, indent=2), True, report)

    config.reset_cache()
    return report
