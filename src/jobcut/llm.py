"""llm.py — optional LLM helper (capability check + one-shot completion).

Wraps anthropic / openai IF the library is installed and a key is available
(environment or <data>/.env). Returns None when no LLM is configured, so every
caller degrades gracefully to a deterministic floor.

Used by the CV importer (profile drafting, cv.py) and interview-round extraction
(process.py) — NOT by scoring, which is rule_based (pure Python) or claude_skills
(judged in Claude). So the `[llm]` extra is optional polish, never on the scoring path.
"""

from __future__ import annotations

import os

from . import paths


def _key(name: str) -> str | None:
    val = os.environ.get(name)
    if val:
        return val
    env = paths.data_dir() / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{name}=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip() or None
    return None


def _anthropic_key() -> str | None:
    return _key("ANTHROPIC_API_KEY")


def _openai_key() -> str | None:
    return _key("OPENAI_API_KEY")


def available() -> bool:
    """True if some provider lib is importable AND its key is set."""
    if _anthropic_key():
        try:
            import anthropic  # noqa: F401
            return True
        except ImportError:
            pass
    if _openai_key():
        try:
            import openai  # noqa: F401
            return True
        except ImportError:
            pass
    return False


def complete(prompt: str, system: str | None = None, max_tokens: int = 1500) -> str | None:
    """One-shot completion. Returns the text, or None if no LLM is configured."""
    ak = _anthropic_key()
    if ak:
        try:
            import anthropic
        except ImportError:
            ak = None
        else:
            client = anthropic.Anthropic(api_key=ak)
            msg = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=max_tokens,
                system=system or "",
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")

    ok = _openai_key()
    if ok:
        try:
            import openai
        except ImportError:
            return None
        client = openai.OpenAI(api_key=ok)
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
        resp = client.chat.completions.create(model="gpt-4o-mini", max_tokens=max_tokens, messages=msgs)
        return resp.choices[0].message.content
    return None
