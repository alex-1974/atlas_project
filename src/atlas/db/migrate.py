from __future__ import annotations

from pathlib import Path

from atlas.db.connection import get_connection
from atlas.settings import get_project_root


def get_migration_dir() -> Path:
    return get_project_root() / "migrations"


def ensure_schema_migrations_table() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                create table if not exists schema_migrations (
                    migration_name text primary key,
                    applied_at timestamptz not null default now()
                );
                """
            )


def get_applied_migrations() -> set[str]:
    ensure_schema_migrations_table()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select migration_name from schema_migrations")
            return {row[0] for row in cur.fetchall()}


def mark_migration_applied(migration_name: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into schema_migrations (migration_name)
                values (%s)
                on conflict (migration_name) do nothing
                """,
                (migration_name,),
            )


def run_migrations() -> None:
    migration_dir = get_migration_dir()
    files = sorted(migration_dir.glob("*.sql"))
    applied = get_applied_migrations()

    for path in files:
        if path.name in applied:
            print(f"skipped migration: {path.name}")
            continue

        sql = path.read_text(encoding="utf-8")

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)

        mark_migration_applied(path.name)
        print(f"applied migration: {path.name}")
