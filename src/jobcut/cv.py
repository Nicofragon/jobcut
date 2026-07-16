"""cv.py — turn an uploaded CV into a profile.md draft.

Floor (always works, no AI, no heavy deps): plain-text/markdown is read directly;
the text is dropped into a profile.md scaffold with the standard headings for the
user to organize. PDF/DOCX are optional (pypdf / python-docx via `jobcut[cv]`).

AI layer (optional): if an LLM is configured (see llm.py), the model fills the
headings from the CV. Either way the result is a DRAFT the user reviews and saves
— nothing is written automatically.
"""

from __future__ import annotations

import io

from . import llm


class CvError(ValueError):
    """A CV could not be read (unsupported type or missing optional dependency)."""


def extract_text(filename: str, data: bytes) -> str:
    ext = (filename or "").lower().rsplit(".", 1)[-1]
    if ext in ("txt", "md", "markdown", "text"):
        return data.decode("utf-8", "ignore")
    if ext == "pdf":
        try:
            import pypdf
        except ImportError as e:
            raise CvError("PDF support needs `pip install jobcut[cv]` — or paste the text instead.") from e
        try:
            reader = pypdf.PdfReader(io.BytesIO(data))
            return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
        except Exception as e:  # corrupt / encrypted / image-only PDF
            raise CvError("Couldn't read that PDF — it may be corrupt or image-only. Paste the text instead.") from e
    if ext == "docx":
        try:
            import docx
        except ImportError as e:
            raise CvError("DOCX support needs `pip install jobcut[cv]` — or paste the text instead.") from e
        try:
            return "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs).strip()
        except Exception as e:  # corrupt / not a real .docx
            raise CvError("Couldn't read that DOCX — it may be corrupt. Paste the text instead.") from e
    raise CvError(f"unsupported file type '.{ext}' — use txt, md, pdf or docx, or paste the text.")


_HEADINGS = ["Target roles", "Seniority", "Core skills", "Nice-to-have / learning",
             "Skill gaps", "Location & work mode", "Dealbreakers"]

_AI_SYSTEM = (
    "You convert a CV into a jobcut profile.md. Output ONLY markdown with EXACTLY these "
    "level-2 headings, in this order: "
    "'## Target roles' (bulleted job titles the person should target), "
    "'## Seniority' (one line), "
    "'## Core skills' (bulleted skills they can clearly do today — their strengths), "
    "'## Nice-to-have / learning' (bulleted skills they have SOME exposure to but wouldn't "
    "claim as core), "
    "'## Skill gaps' (bulleted skills their target roles commonly require that the CV does "
    "NOT evidence — leave empty if none stand out), "
    "'## Location & work mode' (lines 'Based in: ...' and 'Remote: yes/hybrid only/on-site only'), "
    "'## Dealbreakers' (bulleted hard constraints). "
    "Split skills honestly across Core / Nice-to-have / Skill gaps by how strongly the CV "
    "evidences each. Infer reasonably; leave a section's bullets empty if unknown. No preamble."
)


def _ai_draft(text: str) -> str | None:
    if not text or not llm.available():
        return None
    return llm.complete(f"CV:\n\n{text}", system=_AI_SYSTEM)


def _scaffold(text: str) -> str:
    body = ["# My profile",
            "",
            "> Draft scaffold — move the relevant bits from your CV (bottom) into the",
            "> sections below. The filled sections drive your searches and scoring.",
            ""]
    for h in _HEADINGS:
        body.append(f"## {h}")
        if h == "Location & work mode":
            body += ["- Based in: <your city/country>", "- Remote: yes / hybrid only / on-site only", ""]
        else:
            body += ["- ", ""]
    body += ["## Notes for the scorer", "", "<!-- raw CV text below — organize it into the sections above -->", "", text or ""]
    return "\n".join(body)


def draft_profile(text: str) -> dict:
    """Return {profile_md, source}. source = 'ai' when an LLM filled it, else 'scaffold'."""
    ai = _ai_draft(text)
    if ai and ai.strip():
        return {"profile_md": ai.strip() + "\n", "source": "ai"}
    return {"profile_md": _scaffold(text), "source": "scaffold"}
