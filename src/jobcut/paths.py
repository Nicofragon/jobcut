"""Resolve where jobcut reads/writes local data, config and outputs.

The original private pipeline used ``Path(__file__).parent`` as both code and
data dir. Once packaged, code lives under site-packages, so data must live
elsewhere. Resolution order for the data dir:

1. ``$JOBCUT_DATA_DIR`` if set.
2. The current working directory.

Every data file (the SQLite database, xlsx exports, ``last_runs.json``,
``batches/``) and the ``out/`` output dir live under the data dir. Nothing is
ever written next to the installed package.
"""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    """Root directory for all local data, config and outputs."""
    env = os.environ.get("JOBCUT_DATA_DIR")
    return Path(env).expanduser().resolve() if env else Path.cwd()


def searches_dir() -> Path:
    """Directory holding the saved-search JSON files."""
    return data_dir() / "searches"


def config_dir() -> Path:
    """Directory holding taxonomy.json and other config."""
    return data_dir() / "config"


def documents_dir() -> Path:
    """Drop-folder for prep documents (B-22). A markdown file with a ``jobcut:``
    frontmatter block left here is auto-imported into its application by `jobcut serve`
    (or `jobcut import-docs`). Lives under the data dir so it ships with the install and
    works for any user out of the box — never the vault, never iCloud."""
    return data_dir() / "documents"


def out_dir() -> Path:
    """Directory for human/dashboard outputs (Markdown/CSV/HTML). Created on demand."""
    d = data_dir() / "out"
    d.mkdir(parents=True, exist_ok=True)
    return d
