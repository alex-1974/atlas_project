#!/usr/bin/env python3
# tools/docstring_audit.py

"""
Audit Python docstrings.

Reports missing documentation for:

- modules
- classes
- functions
- methods

No code is modified.
"""

from __future__ import annotations

import ast
from pathlib import Path
from collections import defaultdict


PROJECT_ROOT = Path(".").resolve()

INCLUDE_PATTERNS = [
    "bvillage/**/*.py",
]

EXTRA_FILES = [
    PROJECT_ROOT / "run_in_blender.py",
]

EXCLUDE_PATTERNS = [
    "__pycache__",
    ".venv",
    "venv",
    "generated",
    "tests",
    "build",
    "dist",
]


def should_skip(path: Path):

    for part in path.parts:
        if part in EXCLUDE_PATTERNS:
            return True

    return False


def collect_files():

    files = set()

    for pattern in INCLUDE_PATTERNS:
        for p in PROJECT_ROOT.glob(pattern):
            if p.is_file():
                files.add(p.resolve())

    for p in EXTRA_FILES:
        if p.exists():
            files.add(p.resolve())

    return sorted(files)


def module_name(path: Path):

    rel = path.relative_to(PROJECT_ROOT)

    if rel.name == "run_in_blender.py":
        return "run_in_blender"

    if rel.name == "__init__.py":
        rel = rel.parent
    else:
        rel = rel.with_suffix("")

    return ".".join(rel.parts)


def analyze_file(path: Path):

    text = path.read_text(encoding="utf-8")

    tree = ast.parse(text)

    mod_missing = ast.get_docstring(tree) is None

    classes_missing = []
    functions_missing = []

    module = module_name(path)

    for node in tree.body:

        if isinstance(node, ast.ClassDef):

            if ast.get_docstring(node) is None:
                classes_missing.append(f"{module}.{node.name}")

            for item in node.body:

                if isinstance(item, ast.FunctionDef):

                    if ast.get_docstring(item) is None:
                        functions_missing.append(
                            f"{module}.{node.name}.{item.name}"
                        )

        elif isinstance(node, ast.FunctionDef):

            if ast.get_docstring(node) is None:
                functions_missing.append(f"{module}.{node.name}")

    return mod_missing, classes_missing, functions_missing


def main():

    files = collect_files()

    modules_missing = []
    classes_missing = []
    functions_missing = []

    for p in files:

        if should_skip(p):
            continue

        mod_missing, cls_miss, fn_miss = analyze_file(p)

        module = module_name(p)

        if mod_missing:
            modules_missing.append(module)

        classes_missing.extend(cls_miss)
        functions_missing.extend(fn_miss)

    print("\nDOCSTRING AUDIT")
    print("================\n")

    print("Modules missing docstrings:", len(modules_missing))

    for m in modules_missing:
        print("-", m)

    print("\nClasses missing docstrings:", len(classes_missing))

    for c in classes_missing:
        print("-", c)

    print("\nFunctions missing docstrings:", len(functions_missing))

    for f in functions_missing:
        print("-", f)

    if modules_missing or classes_missing or functions_missing:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
