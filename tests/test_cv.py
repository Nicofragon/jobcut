"""Tests for cv.py — text extraction + profile drafting (floor, no LLM)."""

import pytest

from jobcut import cv


def test_extract_txt_and_md():
    assert cv.extract_text("resume.txt", b"Hello CV") == "Hello CV"
    assert "Skills" in cv.extract_text("resume.md", b"# Skills\nSQL")


def test_extract_unsupported_type_raises():
    with pytest.raises(cv.CvError):
        cv.extract_text("resume.rtf", b"data")


def test_extract_pdf_without_lib_points_to_extra():
    # pypdf is an optional dependency; without it the error names the extra.
    pytest.importorskip  # keep import-time light
    try:
        import pypdf  # noqa: F401
        pytest.skip("pypdf installed; the missing-dependency path is not exercised")
    except ImportError:
        with pytest.raises(cv.CvError, match=r"jobcut\[cv\]"):
            cv.extract_text("resume.pdf", b"%PDF-1.4")


def test_extract_docx_roundtrip():
    """When python-docx is available ([cv] extra), .docx text is extracted."""
    docx = pytest.importorskip("docx")
    import io

    doc = docx.Document()
    doc.add_paragraph("Registered Nurse")
    doc.add_paragraph("ACLS, triage")
    buf = io.BytesIO()
    doc.save(buf)
    text = cv.extract_text("resume.docx", buf.getvalue())
    assert "Registered Nurse" in text and "triage" in text


def test_draft_profile_floor_scaffold():
    out = cv.draft_profile("10 years as a Registered Nurse. ACLS, triage.")
    assert out["source"] == "scaffold"        # no LLM configured in tests
    md = out["profile_md"]
    assert "## Target roles" in md and "## Core skills" in md
    assert "Registered Nurse" in md           # raw CV text embedded for organizing


def test_draft_profile_empty_text():
    out = cv.draft_profile("")
    assert out["source"] == "scaffold"
    assert "## Dealbreakers" in out["profile_md"]
