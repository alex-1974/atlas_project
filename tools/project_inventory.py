#!/usr/bin/env python3
"""Create a simple project inventory for Atlas-like packages.

Default Atlas layout:
    atlas_project/tools/project_inventory.py
    atlas_project/src/atlas/
    atlas_project/generated/project_inventory.md

Optional usage:
    python tools/project_inventory.py
    python tools/project_inventory.py --package src/atlas --out generated/project_inventory.md
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ModuleStat:
    path: Path
    lines: int
    classes: int
    functions: int


def module_stats(py_file: Path) -> ModuleStat:
    text = py_file.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(py_file))
    classes = sum(isinstance(node, ast.ClassDef) for node in ast.walk(tree))
    functions = sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.walk(tree))
    return ModuleStat(path=py_file, lines=len(text.splitlines()), classes=classes, functions=functions)


def build_report(package_root: Path) -> str:
    stats = [module_stats(p) for p in sorted(package_root.rglob("*.py"))]
    out: list[str] = ["# Project Inventory", ""]
    out += [f"Package root: `{package_root}`", ""]
    out += ["## Modules", ""]
    out += ["| File | Lines | Classes | Functions |", "|---|---:|---:|---:|"]
    for stat in stats:
        out.append(
            f"| {stat.path.relative_to(package_root)} | {stat.lines} | {stat.classes} | {stat.functions} |"
        )
    out += ["", "## Largest Modules", ""]
    for stat in sorted(stats, key=lambda x: x.lines, reverse=True)[:15]:
        out.append(f"- `{stat.path.relative_to(package_root)}` — {stat.lines} lines")
    out.append("")
    return "\n".join(out)


def main() -> None:
    script_path = Path(__file__).resolve()
    default_root = script_path.parents[1]

    parser = argparse.ArgumentParser()
    parser.add_argument("--package", default=str(default_root / "src" / "atlas"))
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    package_root = Path(args.package).resolve()
    out_path = Path(args.out).resolve() if args.out else (default_root / "generated" / "project_inventory.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    out_path.write_text(build_report(package_root), encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
