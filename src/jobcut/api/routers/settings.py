"""Profile, config, credentials, health — the onboarding/settings surface."""

from __future__ import annotations

import os
import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ... import config, db, export as export_mod, paths, profile as profile_mod
from ..deps import get_conn

router = APIRouter(tags=["settings"])


# --- profile ----------------------------------------------------------------

class ProfileIn(BaseModel):
    content: str


class DeriveIn(BaseModel):
    force: bool = False
    targets: list[str] | None = None


def _profile_path():
    return paths.data_dir() / "profile.md"


@router.get("/profile")
def get_profile():
    p = _profile_path()
    return {"content": p.read_text() if p.exists() else ""}


@router.put("/profile")
def put_profile(body: ProfileIn):
    p = _profile_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body.content)
    return {"content": body.content}


@router.get("/profile/structured", response_model=profile_mod.ProfileFields)
def get_profile_structured():
    """Parse profile.md into the form-friendly structured fields (round-trips with raw)."""
    p = _profile_path()
    return profile_mod.to_structured(p.read_text() if p.exists() else "")


@router.put("/profile/structured", response_model=profile_mod.ProfileFields)
def put_profile_structured(fields: profile_mod.ProfileFields):
    """Write profile.md from structured fields, preserving unmodeled sections (e.g. Notes)."""
    p = _profile_path()
    base = p.read_text() if p.exists() else ""
    md = profile_mod.from_structured(fields, base_md=base)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(md)
    return profile_mod.to_structured(md)


@router.get("/profile/derived")
def get_derived():
    """Preview the searches + rubric derived from profile.md (no file writes)."""
    pd = profile_mod.load()
    return {
        "searches": profile_mod.derive_searches(pd),
        "config": profile_mod.derive_config(pd),
        "taxonomy": profile_mod.derive_taxonomy(pd),
    }


@router.post("/profile/derive")
def post_derive(body: DeriveIn):
    """Write derived artifacts (non-destructive unless force=true)."""
    return profile_mod.apply(force=body.force, targets=body.targets)


# --- config -----------------------------------------------------------------

class ConfigIn(BaseModel):
    config: dict


@router.get("/config")
def get_config():
    """The merged, effective config (DEFAULTS + config.json overrides)."""
    return config.load()


@router.put("/config")
def put_config(body: ConfigIn):
    """Persist overrides to config/config.json, deep-merged so a partial save
    (e.g. scoring weights) never wipes sibling keys like scoring.backend."""
    return config.update(body.config)


# --- credentials ------------------------------------------------------------

class CredentialsIn(BaseModel):
    apify_token: str | None = None
    llm_key: str | None = None


def _env_path():
    return paths.data_dir() / ".env"


def _read_env() -> dict:
    p = _env_path()
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


_PLACEHOLDER = "apify_api_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


def _token_set(value: str | None) -> bool:
    return bool(value) and value != _PLACEHOLDER


@router.get("/credentials")
def get_credentials():
    env = _read_env()
    apify = env.get("APIFY_TOKEN") or os.environ.get("APIFY_TOKEN")
    llm = env.get("OPENAI_API_KEY") or env.get("ANTHROPIC_API_KEY")
    return {"apify_token_set": _token_set(apify), "llm_key_set": _token_set(llm)}


@router.put("/credentials")
def put_credentials(body: CredentialsIn):
    env = _read_env()
    if body.apify_token is not None:
        env["APIFY_TOKEN"] = body.apify_token
    if body.llm_key is not None:
        env["ANTHROPIC_API_KEY"] = body.llm_key
    p = _env_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(f"{k}={v}\n" for k, v in env.items()))
    return get_credentials()


@router.post("/validate-credentials")
def validate_credentials(body: CredentialsIn):
    """Validate WITHOUT spending money: Apify via user().get() (no actor run)."""
    result = {"apify": {"valid": False}, "llm": {"valid": False}}
    if _token_set(body.apify_token):
        try:
            from apify_client import ApifyClient
            user = ApifyClient(body.apify_token).user().get()
            # apify-client 3.x returns a typed UserPrivateInfo object (not a dict).
            result["apify"] = {"valid": True, "username": getattr(user, "username", None)}
        except Exception as exc:
            result["apify"] = {"valid": False, "error": str(exc)}
    # An LLM key can't be checked without a (billable) call; treat presence as valid-ish.
    result["llm"] = {"valid": _token_set(body.llm_key)}
    return result


# --- health -----------------------------------------------------------------

@router.post("/export")
def export(conn: sqlite3.Connection = Depends(get_conn)):
    """Write out/jobs.csv, scores.csv, dashboard.json. Returns the summary + dir."""
    summary = export_mod.main(conn)
    return {"out_dir": str(paths.out_dir()), "summary": summary}


@router.get("/status")
def status(conn: sqlite3.Connection = Depends(get_conn)):
    ver = conn.execute("SELECT value FROM _meta WHERE key='schema_version'").fetchone()
    creds = get_credentials()
    return {
        "data_dir": str(paths.data_dir()),
        "db_path": str(db.db_path()),
        "schema_version": int(ver["value"]) if ver else None,
        "jobs": db.count_jobs(conn),
        "applications": len(db.read_applications(conn)),
        **creds,
    }
