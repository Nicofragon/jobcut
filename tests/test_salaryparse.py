"""B-17: pull a disclosed salary out of the description body (display-only)."""

import pytest

from jobcut.salaryparse import annual_eur_band, job_annual_band
from jobcut.salaryparse import salary_text_from_description as f


@pytest.mark.parametrize("text,expected", [
    ("Salary: Up to 60K€ + 20% variable", "Salary: Up to 60K€ + 20% variable"),
    ("Banda salarial: 45.000 - 55.000 € brutos anuales",
     "Banda salarial: 45.000 - 55.000 € brutos anuales"),
    ("We offer a pay range of $90,000-$120,000 USD",
     "We offer a pay range of $90,000-$120,000 USD"),
    # picks out the salary sentence from surrounding prose (and keeps "30.000" intact)
    ("Trabajamos de 9 a 18. Salario: 30.000€ brutos. Otras cosas.", "Salario: 30.000€ brutos"),
])
def test_extracts(text, expected):
    assert f(text) == expected


@pytest.mark.parametrize("text", [
    None,
    "",
    "Sueldo competitivo según experiencia",                          # salary word, no figure
    "Acceso a Retribución Flexible: Seguro Médico, Cheque Gourmet",  # benefits, no figure
    "En 2022 alcanzamos una facturación de 100M con 40 delegaciones",  # figures, no salary word
    "Buscamos un analista con 5 años de experiencia",               # number, not pay
])
def test_no_false_positive(text):
    assert f(text) is None


# --- annual_eur_band: phrase → (min, max) EUR/year gross -----------------------------------

@pytest.mark.parametrize("phrase,expected", [
    ("Banda salarial: 45.000 - 55.000 € brutos anuales", (45000, 55000)),  # ES thousands range
    ("Salary: Up to 60K€ + 20% variable", (60000, 60000)),                 # k suffix, ignores 20%
    ("Retribución: 2.500 €/mes", (30000, 30000)),                          # monthly → ×12
    ("Salario 30.000€ brutos", (30000, 30000)),                            # single annual figure
    ("Pay range 40k-50k EUR", (40000, 50000)),                             # k on both bounds
    ("Sueldo de 60 mil euros anuales", (60000, 60000)),                    # "mil"
])
def test_annual_eur_band(phrase, expected):
    assert annual_eur_band(phrase) == expected


@pytest.mark.parametrize("phrase", [
    None,
    "",
    "We offer $90,000-$120,000 USD",          # non-EUR → dropped (no FX)
    "Rate: 25 €/hora",                        # hourly → dropped
    "Salario competitivo según valía",        # no figure
    "Con 5 años de experiencia y 3 idiomas",  # bare counts, not pay
])
def test_annual_eur_band_none(phrase):
    assert annual_eur_band(phrase) is None


def test_job_annual_band_prefers_structured():
    # structured min/max win over the description body
    assert job_annual_band("50000", "70000", None, "Salario: 30.000€") == (50000, 70000)


def test_job_annual_band_falls_back_to_description():
    band = job_annual_band(None, None, None, "Trabajamos de 9 a 18. Salario: 42.000€ brutos. Fin.")
    assert band == (42000, 42000)


def test_job_annual_band_none_when_nothing():
    assert job_annual_band(None, None, None, "Sueldo competitivo") is None
