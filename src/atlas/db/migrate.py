# src/atlas/db/migrate.py
from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    sql: str


def _migrations_dir() -> Path:
    return Path(__file__).resolve().parent / "migrations"


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     TEXT PRIMARY KEY,
            applied_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


def _load_migrations() -> list[Migration]:
    migrations_dir = _migrations_dir()
    if not migrations_dir.exists():
        return []
    migrations: list[Migration] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        migrations.append(Migration(
            version=path.stem,
            path=path,
            sql=path.read_text(encoding="utf-8"),
        ))
    return migrations


def _applied_versions(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row["version"] for row in rows}


def run_migrations(conn: sqlite3.Connection) -> None:
    """Apply all pending migrations in version order."""
    _ensure_migrations_table(conn)
    applied = _applied_versions(conn)
    for migration in _load_migrations():
        if migration.version in applied:
            continue
        conn.executescript(migration.sql)
        conn.execute(
            "INSERT INTO schema_migrations (version) VALUES (?)",
            (migration.version,),
        )
        conn.commit()


def assert_schema_current(conn: sqlite3.Connection) -> None:
    """Raise if any migration has not been applied."""
    _ensure_migrations_table(conn)
    available = {m.version for m in _load_migrations()}
    missing = sorted(available - _applied_versions(conn))
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            f"Catalog schema is outdated — missing migrations: {joined}. "
            f"Run 'atlas dev db migrate' to update."
        )


def list_applied(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all applied migrations ordered by version."""
    _ensure_migrations_table(conn)
    return conn.execute(
        "SELECT version, applied_at FROM schema_migrations ORDER BY version"
    ).fetchall()
