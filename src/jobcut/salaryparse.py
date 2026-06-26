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

# A salary keyword (EN + ES). "retribución/remuneración/compensación" included, but a
# figure must also be present (below), so "Retribución Flexible: Seguro Médico…" (no
# amount) is not matched.
_SALARY_KW = re.compile(
    r"\b(salary|salaries|salario|sueldo|retribuci[oó]n|remuneraci[oó]n|"
    r"compensaci[oó]n|paquete\s+salarial|banda\s+salarial|pay\s+range|compensation)\b",
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


def salary_text_from_description(text: str | None) -> str | None:
    """Return the disclosed-salary phrase found in `text`, or None.

    Scans sentence/line segments; returns the first short segment that names a salary
    AND carries a monetary figure, whitespace-collapsed and capped."""
    if not text:
        return None
    # Split on newlines/semicolons and sentence-ending periods, but NOT on a period
    # between digits (so European thousands like "45.000" stay intact).
    for seg in re.split(r"[\n;]+|\.(?=\s|$)", str(text)):
        seg = seg.strip()
        if not seg or len(seg) > _MAX_SEG:
            continue
        if not _MONEY.search(seg) or not _SALARY_KW.search(seg):
            continue
        return re.sub(r"\s+", " ", seg).strip(" -–·:")[:_OUT_CAP]
    return None
