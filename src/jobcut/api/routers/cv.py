"""CV import — extract text and draft a profile.md (AI-optional, manual fallback)."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ... import cv

router = APIRouter(tags=["cv"])


class FromCvIn(BaseModel):
    text: str


@router.post("/cv/extract")
async def extract(file: UploadFile = File(...)):
    """Extract plain text from an uploaded CV (txt/md always; pdf/docx if jobcut[cv])."""
    data = await file.read()
    try:
        text = cv.extract_text(file.filename or "cv.txt", data)
    except cv.CvError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"filename": file.filename, "text": text}


@router.post("/profile/from-cv")
def from_cv(body: FromCvIn):
    """Draft a profile.md from CV text. Returns a draft to review — never saved."""
    return cv.draft_profile(body.text)
