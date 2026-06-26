"""B-17: pull a disclosed salary out of the description body (display-only)."""

import pytest

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
