# src/atlas/db/connection.py
"""SQLite connection helpers for Atlas.

Two interfaces:

1. connect(db_path) → Connection
   Explicit, used by the new pipeline architecture (catalog/add.py,
   pipeline/runner.py). Caller manages the connection lifecycle.

2. get_connection() → context manager
   Used by the old extraction modules (extract/*.py, normalize/*.py).
   Reads the current catalog path from _current_catalog_path (set by
   runner.py via set_catalog_path() before running extraction steps).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


# ── Thread-local catalog path ─────────────────────────────────────────────────
# set_catalog_path() is called by runner.py before invoking old-style modules.

_current_catalog_path: Path | None = None


def set_catalog_path(catalog_root: Path) -> None:
    """Set the active catalog root for get_connection()."""
    global _current_catalog_path
    _current_catalog_path = catalog_root / ".atlas" / "catalog.db"


def _get_db_path() -> Path:
    if _current_catalog_path is None:
        raise RuntimeError(
            "No catalog path set. Call set_catalog_path() before using "
            "get_connection(), or use connect(db_path) directly."
        )
    return _current_catalog_path


# ── New-style explicit connection ─────────────────────────────────────────────

def connect(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with the required Atlas pragmas.

    Creates parent directories if they don't exist yet.
    Caller is responsible for closing the connection.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


# ── Old-style context manager ─────────────────────────────────────────────────

@contextmanager
def get_connection():
    """Context manager returning a SQLite connection for the active catalog.

    Used by old-style extraction modules. Requires set_catalog_path()
    to have been called first.

    Usage:
        with get_connection() as conn:
            conn.execute(...)
    """
    db_path = _get_db_path()
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
