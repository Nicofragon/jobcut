"""Saved-search CRUD. One file `searches/<name>.json` = one search."""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ... import paths, searches as searches_mod

router = APIRouter(prefix="/searches", tags=["searches"])

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")  # no path traversal / extensions


class SearchIn(BaseModel):
    name: str | None = None
    input: dict


def _path(name: str):
    if not _NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="invalid search name")
    return paths.searches_dir() / f"{name}.json"


@router.get("")
def list_searches():
    d = paths.searches_dir()
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        try:
            out.append({"name": f.stem, "input": json.loads(f.read_text())})
        except json.JSONDecodeError:
            out.append({"name": f.stem, "input": None, "error": "invalid json"})
    return out


# --- structured layer (B2) --------------------------------------------------
# Declared BEFORE the /{name} routes so "/searches/structured" isn't captured as
# a search named "structured". Writes the canonical searches/<name>.json actor input.

@router.get("/structured", response_model=list[searches_mod.StructuredSearch])
def list_structured():
    d = paths.searches_dir()
    out = []
    if d.exists():
        for f in sorted(d.glob("*.json")):
            try:
                out.append(searches_mod.from_actor_input(f.stem, json.loads(f.read_text())))
            except json.JSONDecodeError:
                continue
    return out


@router.get("/structured/{name}", response_model=searches_mod.StructuredSearch)
def get_structured(name: str):
    p = _path(name)
    if not p.exists():
        raise HTTPException(status_code=404, detail="search not found")
    return searches_mod.from_actor_input(name, json.loads(p.read_text()))


@router.post("/structured", response_model=searches_mod.StructuredSearch)
def create_structured(body: searches_mod.StructuredSearch):
    if not body.name:
        raise HTTPException(status_code=400, detail="name is required")
    p = _path(body.name)
    if p.exists():
        raise HTTPException(status_code=409, detail="search already exists")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(searches_mod.to_actor_input(body), indent=2))
    return searches_mod.from_actor_input(body.name, json.loads(p.read_text()))


@router.put("/structured/{name}", response_model=searches_mod.StructuredSearch)
def update_structured(name: str, body: searches_mod.StructuredSearch):
    p = _path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(searches_mod.to_actor_input(body), indent=2))
    return searches_mod.from_actor_input(name, json.loads(p.read_text()))


@router.delete("/structured/{name}")
def delete_structured(name: str):
    p = _path(name)
    if not p.exists():
        raise HTTPException(status_code=404, detail="search not found")
    p.unlink()
    return {"deleted": name}


@router.get("/{name}")
def get_search(name: str):
    p = _path(name)
    if not p.exists():
        raise HTTPException(status_code=404, detail="search not found")
    return {"name": name, "input": json.loads(p.read_text())}


@router.post("")
def create_search(body: SearchIn):
    if not body.name:
        raise HTTPException(status_code=400, detail="name is required")
    p = _path(body.name)
    if p.exists():
        raise HTTPException(status_code=409, detail="search already exists")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(body.input, indent=2))
    return {"name": body.name, "input": body.input}


@router.put("/{name}")
def update_search(name: str, body: SearchIn):
    p = _path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(body.input, indent=2))
    return {"name": name, "input": body.input}


@router.delete("/{name}")
def delete_search(name: str):
    p = _path(name)
    if not p.exists():
        raise HTTPException(status_code=404, detail="search not found")
    p.unlink()
    return {"deleted": name}
