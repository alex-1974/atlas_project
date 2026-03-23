#!/usr/bin/env python3
"""Generate a schema report from SQL migration files.

Default Atlas layout:
    atlas_project/tools/db_schema_report.py
    atlas_project/migrations/
    atlas_project/generated/db_schema.md

Optional usage:
    python tools/db_schema_report.py
    python tools/db_schema_report.py --migrations migrations --out generated/db_schema.md
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path

CREATE_TABLE_RE = re.compile(r"create\s+table\s+(?:if\s+not\s+exists\s+)?([a-zA-Z_][\w]*)\s*\((.*?)\);", re.I | re.S)
CREATE_INDEX_RE = re.compile(r"create\s+(?:unique\s+)?index\s+([a-zA-Z_][\w]*)\s+on\s+([a-zA-Z_][\w]*)\s*\((.*?)\)", re.I | re.S)
ALTER_ADD_COL_RE = re.compile(r"alter\s+table\s+([a-zA-Z_][\w]*)\s+add\s+column\s+([a-zA-Z_][\w]*)\s+(.*?);", re.I | re.S)
REF_RE = re.compile(r"references\s+([a-zA-Z_][\w]*)\s*\(([^)]+)\)", re.I)


@dataclass
class Column:
    name: str
    definition: str
    references: str | None = None


@dataclass
class Table:
    name: str
    columns: list[Column] = field(default_factory=list)
    indexes: list[str] = field(default_factory=list)
    defined_in: set[str] = field(default_factory=set)


def split_columns(block: str) -> list[str]:
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    for ch in block:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            item = ''.join(cur).strip()
            if item:
                parts.append(item)
            cur = []
            continue
        cur.append(ch)
    tail = ''.join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


def parse_tables(sql_text: str, source_name: str, tables: dict[str, Table]) -> None:
    for match in CREATE_TABLE_RE.finditer(sql_text):
        table_name = match.group(1)
        body = match.group(2)
        table = tables.setdefault(table_name, Table(name=table_name))
        table.defined_in.add(source_name)
        for raw_col in split_columns(body):
            lowered = raw_col.lower()
            if lowered.startswith(("primary key", "foreign key", "unique", "constraint", "check")):
                continue
            pieces = raw_col.split()
            if not pieces:
                continue
            col_name = pieces[0]
            ref_match = REF_RE.search(raw_col)
            ref = None
            if ref_match:
                ref = f"{ref_match.group(1)}({ref_match.group(2).strip()})"
            table.columns.append(Column(name=col_name, definition=raw_col.strip(), references=ref))

    for match in ALTER_ADD_COL_RE.finditer(sql_text):
        table_name, col_name, rest = match.groups()
        table = tables.setdefault(table_name, Table(name=table_name))
        table.defined_in.add(source_name)
        ref_match = REF_RE.search(rest)
        ref = None
        if ref_match:
            ref = f"{ref_match.group(1)}({ref_match.group(2).strip()})"
        table.columns.append(Column(name=col_name, definition=f"{col_name} {rest.strip()}", references=ref))

    for match in CREATE_INDEX_RE.finditer(sql_text):
        idx_name, table_name, cols = match.groups()
        table = tables.setdefault(table_name, Table(name=table_name))
        table.indexes.append(f"{idx_name}({ ' '.join(cols.split()) })")
        table.defined_in.add(source_name)


def build_report(migrations_dir: Path) -> str:
    tables: dict[str, Table] = {}
    for sql_file in sorted(migrations_dir.glob("*.sql")):
        parse_tables(sql_file.read_text(encoding="utf-8"), sql_file.name, tables)

    out: list[str] = ["# Database Schema Report", ""]
    out += [f"Migrations directory: `{migrations_dir}`", ""]

    out += ["## Tables", ""]
    for table_name in sorted(tables):
        table = tables[table_name]
        out.append(f"### {table.name}")
        out.append("")
        out.append(f"Defined in: {', '.join(sorted(table.defined_in))}")
        out.append("")
        out.append("| Column | Definition | References |")
        out.append("|---|---|---|")
        seen: set[tuple[str, str]] = set()
        for col in table.columns:
            key = (col.name, col.definition)
            if key in seen:
                continue
            seen.add(key)
            ref = col.references or ""
            definition = col.definition.replace("|", "\\|")
            out.append(f"| {col.name} | {definition} | {ref} |")
        out.append("")
        if table.indexes:
            out.append("Indexes:")
            for idx in sorted(set(table.indexes)):
                out.append(f"- `{idx}`")
            out.append("")

    out += ["## Relationship Hints", ""]
    for table_name in sorted(tables):
        refs = [(c.name, c.references) for c in tables[table_name].columns if c.references]
        if not refs:
            continue
        out.append(f"- **{table_name}**")
        for col_name, ref in refs:
            out.append(f"  - `{col_name}` -> `{ref}`")
    out.append("")
    return "\n".join(out)


def main() -> None:
    script_path = Path(__file__).resolve()
    default_root = script_path.parents[1]

    parser = argparse.ArgumentParser()
    parser.add_argument("--migrations", default=str(default_root / "migrations"))
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    migrations_dir = Path(args.migrations).resolve()
    out_path = Path(args.out).resolve() if args.out else (default_root / "generated" / "db_schema.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    out_path.write_text(build_report(migrations_dir), encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
