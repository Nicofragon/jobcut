"""Pull a disclosed salary out of a job's free-text description (B-17).

LinkedIn only fills the structured salary fields (salary_min/max/text) when it exposes
pay as structured data. Plenty of listings instead state it in the description body
("Salary: Up to 60K€ + 20% variable", "Banda: 45.000 - 55.000 € brutos/año"). When the
structured fields are empty, this finds that line so the console can show the band the
employer actually published — distinct from a Cowork *estimate* (B-15).

Display-only and conservative: it returns the matched phrase as-is (no min/max guessing),
and only when a salary keyword and a monetary figure appear together — so revenue
figures ("facturación de 100M") and benefit lists ("Retribución Flexible: Seguro…") don't
get misread as pay.
"""

from __future__ import annotations

import re

# A salary keyword (EN + ES + a little FR/IT — the market spans them). A figure must also be
# present (below), so "Retribución Flexible: Seguro Médico…" (no amount) is not matched. These
# are all *strong* pay terms: deliberately NOT bare "annual"/"per year"/"range", which attach to
# benefit lines ("€1K per year for courses") and would bank perks as salary.
_SALARY_KW = re.compile(
    r"\b(salary|salaries|salario|sueldo|retribuci[oó]n|remuneraci[oó]n|"
    r"compensaci[oó]n|compensation|paquete\s+salarial|banda\s+salarial|"
    r"rango\s+salarial|pay\s+range|salary\s+range|total\s+cash|"          # EN/ES ranges
    r"salaire|retribuzione|RAL|"                                          # FR/IT terms
    r"brut[oa]s?\s+anual(?:es)?|brut[oa]s?\s*/\s*a[nñ]o|brut\s+annuel|"   # "gross annual" as a signal
    r"lorda\s+annua|annua\s+lorda)\b",
    re.I,
)

# A monetary figure: a currency-tagged amount, a "60k"/"60 mil", or a "45.000"-style
# thousands amount. Deliberately strict so plain counts (40 delegaciones) don't match.
_MONEY = re.compile(
    r"(?:[€$£]|\bEUR\b|\bUSD\b|\bGBP\b)\s?\d[\d.,]*"          # €60.000 / EUR 60000
    r"|\b\d{1,3}(?:[.,]\d{3})*\s?(?:k\b|mil\b|€|EUR\b)"        # 60k / 60 mil / 45.000€
    r"|\b\d{2,3}\.000\b",                                      # 45.000
    re.I,
)

_MAX_SEG = 200   # ignore very long segments (paragraphs) — a salary line is short
_OUT_CAP = 140   # cap the returned phrase


def _segments(text: str):
    """Yield short candidate segments from a description body.

    Scraped descriptions often glue a salary line onto the previous sentence with no space
    ("…en la posiciónSalario 30.000€…") or run several clauses together past any period, so a
    naive sentence split never isolates the pay line. We first insert a break at lower→Upper
    word joins, then split on newlines/semicolons, commas *followed by space* (never a "45,000"
    thousands comma), and sentence-ending periods (never a "45.000" thousands period)."""
    t = re.sub(r"(?<=[a-zñáéíóú])(?=[A-ZÁÉÍÓÚ])", ". ", str(text))
    for seg in re.split(r"[\n;]+|,(?=\s)|\.(?=\s|$)", t):
        yield seg.strip()


def salary_text_from_description(text: str | None) -> str | None:
    """Return the disclosed-salary phrase found in `text`, or None.

    Returns the first short segment that names a salary AND carries a monetary figure,
    whitespace-collapsed and capped."""
    if not text:
        return None
    for seg in _segments(text):
        if not seg or len(seg) > _MAX_SEG:
            continue
        if not _MONEY.search(seg) or not _SALARY_KW.search(seg):
            continue
        return re.sub(r"\s+", " ", seg).strip(" -–·:")[:_OUT_CAP]
    return None


# --- Numeric band extraction: normalize a disclosed salary to EUR/year gross. -------------
#
# Aggregating disclosed pay across offers (the per-role ranges on Discovery) needs numbers,
# not phrases. This turns a short salary phrase — or the structured salary_min/max fields —
# into an annual-EUR (min, max) band, pragmatically (per the product decision):
#   - EUR only. A $/£/USD/GBP figure returns None; we don't FX-convert the handful we'd find.
#   - "60k"/"60 mil" → 60000; European ("45.000") and English ("90,000") thousands handled.
#   - monthly (/mes, mensual, /month) → ×12; hourly is dropped (too noisy to annualize).
#   - no explicit period → inferred by magnitude (≥12k reads annual, ≥800 monthly, else drop).
# Conservative and lossy on purpose: a value we can't confidently normalize is dropped, so the
# aggregate ranges stay trustworthy even though the sample shrinks.

_NON_EUR = re.compile(r"[$£]|\bUSD\b|\bGBP\b|d[oó]lar", re.I)
_MONTHLY = re.compile(r"/\s*mes|\bmensual(?:es)?\b|/\s*mo(?:nth)?\b|\bper\s+month\b|\bal\s+mes\b", re.I)
_HOURLY = re.compile(r"/\s*h(?:ora|our|r)?\b|\bper\s+hour\b|\bhourly\b|\bpor\s+hora\b", re.I)

# A monetary amount, capturing an optional leading/trailing currency and an optional k/mil.
# The number itself is group 2. We keep an amount only when it carries a currency, a k/mil
# suffix, or a thousands separator — so bare counts ("20% variable", "5 años") are ignored.
_AMOUNT = re.compile(
    r"([€$£]|\bEUR\b|\bUSD\b|\bGBP\b)?\s?"          # 1: leading currency (optional)
    r"(\d{1,3}(?:[.,]\d{3})+|\d{1,3}[.,]\d{1,2}|\d{2,6}|\d{1,3})"  # 2: number (incl. "3.8" for 3.8k)
    r"\s?(k|mil)?"                                  # 3: k/mil (optional)
    r"\s?([€$£]|\bEUR\b|\bUSD\b|\bGBP\b)?",         # 4: trailing currency (optional)
    re.I,
)


def _to_number(digits: str, suffix: str | None) -> float | None:
    """"45.000"/"90,000"/"60k"/"1.5k" → a float magnitude (pre-annualization)."""
    s = re.sub(r"[.,](?=\d{3}(?:\D|$))", "", digits)   # strip thousands separators
    s = s.replace(",", ".")                            # any leftover separator is a decimal
    try:
        val = float(s)
    except ValueError:
        return None
    if (suffix or "").lower() in ("k", "mil"):
        val *= 1000
    return val


# A figure at/above this, with no explicit monthly marker, reads as an annual salary; below it,
# as a monthly one (no EUR full-time annual salary sits under it, monthly ones routinely do).
_MONTHLY_MAX = 6000


def _annualized_band(vals: list[float], has_monthly_word: bool) -> tuple[int, int] | None:
    """A set of raw EUR magnitudes → one (min, max) annual band, deciding monthly-vs-annual ONCE
    for the whole set. Per-value inference would mis-scale a min/max that straddles the threshold
    (e.g. 9700–12000 → 116400–12000). Monthly when an explicit marker is present or the largest
    figure is monthly-sized; then every figure is scaled the same way."""
    if not vals:
        return None
    top = max(vals)
    factor = 12 if (has_monthly_word or top < _MONTHLY_MAX) else 1
    return _clamp_band(min(vals) * factor, top * factor)


def _amounts(text: str) -> list[float]:
    """Raw magnitudes (pre-annualization) worth treating as pay in `text`."""
    vals: list[float] = []
    for m in _AMOUNT.finditer(text):
        if m.end() < len(text) and text[m.end()] == "%":
            continue                            # "+ 20% variable" is not base pay
        digits, suffix = m.group(2), m.group(3)
        has_cur = bool(m.group(1) or m.group(4))
        has_sep = bool(re.search(r"\d[.,]\d{3}", digits))
        if not (suffix or has_sep or has_cur):
            continue                            # a bare number (year, count) — skip
        v = _to_number(digits, suffix)
        if v is not None and v > 0:
            vals.append(v)
    return vals


def _clamp_band(lo: float, hi: float) -> tuple[int, int] | None:
    """Round to a (min, max) band, dropping absurd magnitudes and implausibly wide spreads.

    A real posted range's floor sits within ~40% of its ceiling (e.g. 40k–70k); a band whose
    min is a small fraction of its max (30–25000, 5000–48000) is almost always two unrelated
    figures the text glued together, not one salary — drop it rather than record a junk midpoint."""
    if hi < 8000 or lo > 500000 or lo < hi * 0.35:
        return None
    return (int(round(lo)), int(round(hi)))


def annual_eur_band(phrase: str | None) -> tuple[int, int] | None:
    """A salary phrase → (min, max) EUR/year gross, or None if not a normalizable EUR figure."""
    if not phrase or _NON_EUR.search(phrase) or _HOURLY.search(phrase):
        return None
    return _annualized_band(_amounts(phrase), bool(_MONTHLY.search(phrase)))


def _num_or_none(x) -> float | None:
    try:
        v = float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def job_annual_band(salary_min=None, salary_max=None, salary_text=None,
                    description=None) -> tuple[int, int] | None:
    """Best annual-EUR band for a job: structured min/max first, then salary_text, then the
    description body. Returns None when nothing normalizes to trustworthy EUR/year pay."""
    lo, hi = _num_or_none(salary_min), _num_or_none(salary_max)
    if lo or hi:
        # LinkedIn also stores hourly/garbage pairs here (e.g. 100–1000), so require a plausible
        # full-time annual max before trusting a structured band.
        band = _annualized_band([v for v in (lo, hi) if v],
                                bool(_MONTHLY.search(str(salary_text or ""))))
        if band and band[1] >= 18000:
            return band
    return annual_eur_band(salary_text) or annual_eur_band(
        salary_text_from_description(description))
