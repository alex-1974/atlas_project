#!/usr/bin/env python3
"""Static call and module graph generator for Atlas-like Python projects.

Default Atlas layout:
    atlas_project/tools/call_graph.py
    atlas_project/src/atlas/
    atlas_project/generated/call_graph.md

Goals of this version:
- analyze only intended project code
- skip .venv, venv, caches, generated artifacts, migrations, tests, etc.
- stay robust on syntax/encoding errors
- keep output useful for architecture understanding
- preserve simple Atlas defaults

Examples:
    python tools/call_graph.py --format markdown
    python tools/call_graph.py --format mermaid
    python tools/call_graph.py --include-tests
    python tools/call_graph.py --root . --package src/atlas --out generated/call_graph.md
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


DEFAULT_EXCLUDED_DIRS = {
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "node_modules",
    "generated",
    "build",
    "dist",
    "site-packages",
    "migrations",
    "tools",
}

DEFAULT_EXCLUDED_FILE_PATTERNS = (
    "test_*.py",
    "*_test.py",
)


@dataclass
class FunctionInfo:
    name: str
    qualname: str
    lineno: int
    calls: set[str] = field(default_factory=set)


@dataclass
class ModuleInfo:
    path: Path
    module_name: str
    imports: set[str] = field(default_factory=set)
    functions: dict[str, FunctionInfo] = field(default_factory=dict)
    classes: dict[str, list[str]] = field(default_factory=dict)


class Analyzer(ast.NodeVisitor):
    def __init__(self, module_name: str) -> None:
        self.module = ModuleInfo(path=Path(), module_name=module_name)
        self._func_stack: list[str] = []
        self._class_stack: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name:
                self.module.imports.add(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        if node.level:
            mod = "." * node.level + mod
        if mod:
            self.module.imports.add(mod)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        self.module.classes.setdefault(node.name, [])
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._register_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._register_function(node)

    def _register_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        parts = [*self._class_stack, node.name]
        qualname = ".".join(parts)
        self.module.functions[qualname] = FunctionInfo(
            name=node.name,
            qualname=qualname,
            lineno=node.lineno,
        )
        if self._class_stack:
            self.module.classes[self._class_stack[-1]].append(node.name)

        self._func_stack.append(qualname)
        self.generic_visit(node)
        self._func_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if self._func_stack:
            current = self._func_stack[-1]
            called = self._call_name(node.func)
            if called:
                self.module.functions[current].calls.add(called)
        self.generic_visit(node)

    @staticmethod
    def _call_name(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id

        if isinstance(node, ast.Attribute):
            parts: list[str] = []
            cur: ast.AST | None = node
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
            parts.reverse()
            return ".".join(parts)

        return None


def should_skip_path(
    path: Path,
    *,
    package_root: Path,
    excluded_dirs: set[str],
    include_tests: bool,
) -> bool:
    try:
        rel = path.relative_to(package_root)
    except ValueError:
        return True

    for part in rel.parts[:-1]:
        if part in excluded_dirs:
            return True

    if not include_tests:
        name = path.name
        if name.startswith("test_") or name.endswith("_test.py"):
            return True
        if "tests" in rel.parts:
            return True

    return False


def iter_py_files(
    package_root: Path,
    *,
    excluded_dirs: set[str],
    include_tests: bool,
) -> Iterable[Path]:
    for path in sorted(package_root.rglob("*.py")):
        if not path.is_file():
            continue
        if path.is_symlink():
            continue
        if should_skip_path(
            path,
            package_root=package_root,
            excluded_dirs=excluded_dirs,
            include_tests=include_tests,
        ):
            continue
        yield path


def module_name_from_path(package_root: Path, file_path: Path) -> str:
    rel = file_path.relative_to(package_root.parent)
    return ".".join(rel.with_suffix("").parts)


def analyze_package(
    package_root: Path,
    *,
    excluded_dirs: set[str],
    include_tests: bool,
    verbose: bool = False,
) -> tuple[dict[str, ModuleInfo], list[str]]:
    results: dict[str, ModuleInfo] = {}
    skipped: list[str] = []

    for py_file in iter_py_files(
        package_root,
        excluded_dirs=excluded_dirs,
        include_tests=include_tests,
    ):
        module_name = module_name_from_path(package_root, py_file)

        try:
            source = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            skipped.append(f"{py_file}: unicode decode error")
            continue
        except OSError as exc:
            skipped.append(f"{py_file}: read error ({exc})")
            continue

        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError as exc:
            skipped.append(f"{py_file}: syntax error (line {exc.lineno})")
            continue

        analyzer = Analyzer(module_name)
        analyzer.module.path = py_file
        analyzer.visit(tree)
        results[module_name] = analyzer.module

        if verbose:
            print(f"analyzed: {py_file}")

    return results, skipped


def resolve_relative_import(current_module: str, raw_import: str) -> str:
    if not raw_import.startswith("."):
        return raw_import

    dots = 0
    for ch in raw_import:
        if ch == ".":
            dots += 1
        else:
            break

    suffix = raw_import[dots:]
    parts = current_module.split(".")
    if dots > len(parts):
        return suffix

    base_parts = parts[:-dots]
    if suffix:
        return ".".join(base_parts + [suffix])
    return ".".join(base_parts)


def filter_internal_imports(module_infos: dict[str, ModuleInfo]) -> dict[str, set[str]]:
    known = set(module_infos)
    internal: dict[str, set[str]] = {}

    for mod, info in module_infos.items():
        edges: set[str] = set()

        for imp in info.imports:
            resolved = resolve_relative_import(mod, imp)

            if resolved in known:
                edges.add(resolved)
                continue

            # atlas.foo -> atlas.foo.bar
            prefix_matches = sorted(k for k in known if k.startswith(resolved + "."))
            if prefix_matches:
                edges.add(prefix_matches[0])
                continue

        internal[mod] = edges

    return internal


def render_markdown(module_infos: dict[str, ModuleInfo], skipped: list[str]) -> str:
    imports = filter_internal_imports(module_infos)
    out: list[str] = [
        "# Call Graph Report",
        "",
        f"- modules analyzed: {len(module_infos)}",
        f"- files skipped: {len(skipped)}",
        "",
        "## Module Import Graph",
        "",
    ]

    for mod in sorted(module_infos):
        deps = sorted(imports.get(mod, set()))
        dep_text = ", ".join(deps) if deps else "-"
        out.append(f"- **{mod}** -> {dep_text}")

    out += ["", "## Functions and Local Calls", ""]
    for mod in sorted(module_infos):
        info = module_infos[mod]
        out.append(f"### {mod}")
        out.append("")
        if not info.functions:
            out.append("- no functions")
            out.append("")
            continue

        for fn in sorted(info.functions):
            calls = ", ".join(sorted(info.functions[fn].calls)) or "-"
            out.append(f"- `{fn}` (line {info.functions[fn].lineno}) -> {calls}")
        out.append("")

    if skipped:
        out += ["## Skipped Files", ""]
        for item in skipped:
            out.append(f"- {item}")
        out.append("")

    return "\n".join(out)


def render_mermaid(module_infos: dict[str, ModuleInfo], skipped: list[str]) -> str:
    imports = filter_internal_imports(module_infos)

    out = [
        "# Module Graph",
        "",
        f"- modules analyzed: {len(module_infos)}",
        f"- files skipped: {len(skipped)}",
        "",
        "```mermaid",
        "graph TD",
    ]

    for mod, deps in sorted(imports.items()):
        safe_mod = mod.replace(".", "_").replace("-", "_")
        if not deps:
            out.append(f'    {safe_mod}["{mod}"]')
            continue
        for dep in sorted(deps):
            safe_dep = dep.replace(".", "_").replace("-", "_")
            out.append(f'    {safe_mod}["{mod}"] --> {safe_dep}["{dep}"]')

    out += ["```", "", "# Local Function Calls", "", "```mermaid", "graph TD"]

    for mod, info in sorted(module_infos.items()):
        name_to_qual = {finfo.name: qn for qn, finfo in info.functions.items()}
        for fn_name, fn in sorted(info.functions.items()):
            src_label = f"{mod}.{fn_name}"
            src = src_label.replace(".", "_").replace("-", "_")
            out.append(f'    {src}["{src_label}"]')
            for target in sorted(c for c in fn.calls if c in name_to_qual):
                dst_label = f"{mod}.{name_to_qual[target]}"
                dst = dst_label.replace(".", "_").replace("-", "_")
                out.append(f'    {src} --> {dst}["{dst_label}"]')

    out += ["```"]

    if skipped:
        out += ["", "# Skipped Files", ""]
        for item in skipped:
            out.append(f"- {item}")

    return "\n".join(out)


def parse_args() -> argparse.Namespace:
    script_path = Path(__file__).resolve()
    default_root = script_path.parents[1]

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(default_root))
    parser.add_argument("--package", default="src/atlas")
    parser.add_argument("--format", choices=["markdown", "mermaid"], default="markdown")
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Include test files and tests directories.",
    )
    parser.add_argument(
        "--exclude-dir",
        action="append",
        default=[],
        help="Additional directory name to exclude. Can be used multiple times.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print analyzed files during execution.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    root = Path(args.root).resolve()
    package_root = (root / args.package).resolve()
    out_path = Path(args.out).resolve() if args.out else (root / "generated" / "call_graph.md")

    if not package_root.exists():
        raise SystemExit(f"Package path does not exist: {package_root}")
    if not package_root.is_dir():
        raise SystemExit(f"Package path is not a directory: {package_root}")

    excluded_dirs = set(DEFAULT_EXCLUDED_DIRS)
    excluded_dirs.update(args.exclude_dir)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    module_infos, skipped = analyze_package(
        package_root,
        excluded_dirs=excluded_dirs,
        include_tests=args.include_tests,
        verbose=args.verbose,
    )

    content = (
        render_mermaid(module_infos, skipped)
        if args.format == "mermaid"
        else render_markdown(module_infos, skipped)
    )

    out_path.write_text(content, encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
