#!/usr/bin/env bash
# tools/arch_scan.sh
# Signature-focused architecture scan for Atlas
#
# Purpose:
# - provide a fast structural inventory
# - list module signatures, imports, top-level functions, classes, dataclasses, constants
# - avoid deep architectural judgement; dedicated scripts should do deeper validation
#
# Usage:
#   ./tools/arch_scan.sh
#   ./tools/arch_scan.sh .
#   ./tools/arch_scan.sh . --summary-only
#   ./tools/arch_scan.sh . --json --out tmp/ARCH_SCAN.json
#   ./tools/arch_scan.sh . --archive

set -euo pipefail

ROOT="."
MODE="--text"
OUT_PATH=""
ARCHIVE=0
SUMMARY_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) MODE="--json"; shift ;;
    --text) MODE="--text"; shift ;;
    --summary-only) SUMMARY_ONLY=1; shift ;;
    --archive) ARCHIVE=1; shift ;;
    --out)
      OUT_PATH="${2:-}"
      [[ -z "$OUT_PATH" ]] && { echo "ERROR: --out requires a path" >&2; exit 2; }
      shift 2
      ;;
    -h|--help)
      sed -n '1,120p' "$0"
      exit 0
      ;;
    *)
      if [[ "$1" == -* ]]; then
        echo "ERROR: Unknown flag: $1" >&2
        exit 2
      fi
      ROOT="$1"
      shift
      ;;
  esac
done

ROOT="${ROOT%/}"

if [[ "$ARCHIVE" -eq 1 ]]; then
  ts="$(date +%Y-%m-%d_%H-%M-%S)"
  ext="txt"
  [[ "$MODE" == "--json" ]] && ext="json"
  mkdir -p "$ROOT/docs/archive"
  OUT_PATH="$ROOT/docs/archive/ARCH_SCAN_${ts}.${ext}"
else
  if [[ -z "$OUT_PATH" ]]; then
    if [[ "$MODE" == "--json" ]]; then
      OUT_PATH="$ROOT/generated/ARCH_SCAN.json"
    else
      OUT_PATH="$ROOT/generated/ARCH_SCAN.txt"
    fi
  fi
  mkdir -p "$(dirname "$OUT_PATH")"
fi

PY_FILE="$(mktemp)"
cleanup() { rm -f "$PY_FILE"; }
trap cleanup EXIT

cat > "$PY_FILE" <<'PYEOF'
import ast
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(sys.argv[1]).resolve()
MODE = (sys.argv[2] if len(sys.argv) > 2 else "--text").strip()
SUMMARY_ONLY = (sys.argv[3] if len(sys.argv) > 3 else "0").strip() == "1"

INCLUDE_TOP = ("src/atlas", "tests", "tools")
EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".tox", ".nox", "build", "dist", ".eggs", "node_modules",
    "htmlcov", ".idea", ".vscode", "site-packages",
}

ATLAS_LAYERS = (
    "package", "cli", "settings", "common", "data", "db", "models", "lexicon",
    "metadata", "nlp", "structure", "ingest", "extract", "normalize", "enrich",
    "segment", "search", "inspect", "tests", "tools", "other",
)

@dataclass
class FileReport:
    path: str
    layer: str
    module: str
    header_ok: bool
    header_issue: Optional[str]
    module_docstring: Optional[str]
    all_exports: List[str]
    imports: List[str]
    imported_atlas_modules: List[str]
    constants: List[str]
    functions: List[str]
    classes: List[Dict[str, Any]]
    issues: List[str]


def relpath(p: Path) -> str:
    return p.resolve().relative_to(ROOT).as_posix()


def should_skip(p: Path) -> bool:
    return any(part in EXCLUDE_DIRS for part in p.parts)


def detect_layer(rp: str) -> str:
    if rp == "src/atlas/__init__.py":
        return "package"
    if rp == "src/atlas/cli.py":
        return "cli"
    if rp == "src/atlas/settings.py":
        return "settings"
    for layer in (
        "common", "data", "db", "models", "lexicon", "metadata", "nlp", "structure",
        "ingest", "extract", "normalize", "enrich", "segment", "search", "inspect",
    ):
        if rp.startswith(f"src/atlas/{layer}/"):
            return layer
    if rp.startswith("tests/"):
        return "tests"
    if rp.startswith("tools/"):
        return "tools"
    return "other"


def detect_module(rp: str) -> str:
    if not rp.endswith(".py"):
        return rp.replace("/", ".")
    if rp.startswith("src/"):
        mod = rp[4:-3].replace("/", ".")
        if mod.endswith(".__init__"):
            mod = mod[:-9]
        return mod
    mod = rp[:-3].replace("/", ".")
    if mod.endswith(".__init__"):
        mod = mod[:-9]
    return mod


def first_line(text: str) -> str:
    return text.splitlines()[0] if text else ""


def second_line(text: str) -> str:
    lines = text.splitlines()
    return lines[1] if len(lines) > 1 else ""


def check_header(rp: str, text: str) -> Optional[str]:
    exp = f"# {rp}"
    fl = first_line(text).rstrip("\n")
    if fl.startswith("#!"):
        sl = second_line(text).rstrip("\n")
        if sl.strip() != exp:
            return f"Expected line2 {exp!r}, got {sl!r}"
        return None
    if fl.strip() != exp:
        return f"Expected line1 {exp!r}, got {fl!r}"
    return None


def ann(node: Optional[ast.AST]) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return "?"


def arg_sig(a: ast.arg) -> str:
    s = a.arg
    if a.annotation:
        s += f": {ann(a.annotation)}"
    return s


def func_sig(node: ast.AST) -> str:
    args = node.args
    parts = []
    for a in args.posonlyargs:
        parts.append(arg_sig(a))
    if args.posonlyargs:
        parts.append("/")

    n = len(args.args)
    nd = len(args.defaults)
    offset = n - nd
    for i, a in enumerate(args.args):
        s = arg_sig(a)
        di = i - offset
        if di >= 0:
            try:
                s += f"={ast.unparse(args.defaults[di])}"
            except Exception:
                s += "=..."
        parts.append(s)

    if args.vararg:
        parts.append(f"*{arg_sig(args.vararg)}")
    elif args.kwonlyargs:
        parts.append("*")

    for i, a in enumerate(args.kwonlyargs):
        s = arg_sig(a)
        if args.kw_defaults[i] is not None:
            try:
                s += f"={ast.unparse(args.kw_defaults[i])}"
            except Exception:
                s += "=..."
        parts.append(s)

    if args.kwarg:
        parts.append(f"**{arg_sig(args.kwarg)}")

    ret = f" -> {ann(node.returns)}" if getattr(node, "returns", None) else ""
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({', '.join(parts)}){ret}"


def is_dataclass(node: ast.ClassDef) -> bool:
    for d in node.decorator_list:
        if isinstance(d, ast.Name) and d.id == "dataclass":
            return True
        if isinstance(d, ast.Attribute) and d.attr == "dataclass":
            return True
        if isinstance(d, ast.Call):
            fn = d.func
            if isinstance(fn, ast.Name) and fn.id == "dataclass":
                return True
            if isinstance(fn, ast.Attribute) and fn.attr == "dataclass":
                return True
    return False


def class_entry(node: ast.ClassDef) -> Dict[str, Any]:
    bases = []
    for b in node.bases:
        try:
            bases.append(ast.unparse(b))
        except Exception:
            bases.append("?")
    fields = []
    methods = []
    for item in node.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            entry = item.target.id
            if item.annotation:
                entry += f": {ann(item.annotation)}"
            if item.value is not None:
                try:
                    entry += f" = {ast.unparse(item.value)}"
                except Exception:
                    entry += " = ..."
            fields.append(entry)
        elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(func_sig(item))
    return {
        "name": node.name,
        "bases": bases,
        "is_dataclass": is_dataclass(node),
        "fields": fields,
        "methods": methods,
    }


def parse_imports(tree: ast.AST) -> List[str]:
    out = []
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Import):
            for n in node.names:
                out.append(n.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:
                dots = "." * node.level
                for n in node.names:
                    if n.name == "*":
                        out.append(f"{dots}{mod}.*".strip("."))
                    else:
                        out.append(f"{dots}{mod}.{n.name}".strip("."))
            else:
                for n in node.names:
                    if n.name == "*":
                        out.append(f"{mod}.*".strip("."))
                    else:
                        out.append(f"{mod}.{n.name}".strip("."))
    return out


def atlas_imports(imports: List[str]) -> List[str]:
    out = []
    for imp in imports:
        if imp == "atlas" or imp.startswith("atlas."):
            out.append(imp)
        elif imp == "src.atlas" or imp.startswith("src.atlas."):
            out.append(imp)
        elif imp.startswith("."):
            out.append(imp)
    return sorted(set(out))


def module_docstring(tree: ast.AST) -> Optional[str]:
    try:
        return ast.get_docstring(tree)
    except Exception:
        return None


def find_all_exports(tree: ast.AST) -> List[str]:
    exports = []
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for el in node.value.elts:
                            if isinstance(el, ast.Constant) and isinstance(el.value, str):
                                exports.append(el.value)
    return exports


def find_constants(tree: ast.AST) -> List[str]:
    out = []
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    name = target.id
                    if name.isupper() and not name.startswith("_"):
                        out.append(name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            if name.isupper() and not name.startswith("_"):
                out.append(name)
    return sorted(set(out))


def file_report(pyfile: Path) -> FileReport:
    rp = relpath(pyfile)
    layer = detect_layer(rp)
    module = detect_module(rp)
    text = pyfile.read_text(encoding="utf-8", errors="replace")
    header_issue = check_header(rp, text)
    issues = []
    if header_issue:
        issues.append(header_issue)

    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        issues.append(f"SyntaxError: {e.msg} (line {e.lineno})")
        return FileReport(
            path=rp,
            layer=layer,
            module=module,
            header_ok=header_issue is None,
            header_issue=header_issue,
            module_docstring=None,
            all_exports=[],
            imports=[],
            imported_atlas_modules=[],
            constants=[],
            functions=[],
            classes=[],
            issues=issues,
        )

    funcs = []
    classes = []
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append(func_sig(node))
        elif isinstance(node, ast.ClassDef):
            classes.append(class_entry(node))

    return FileReport(
        path=rp,
        layer=layer,
        module=module,
        header_ok=header_issue is None,
        header_issue=header_issue,
        module_docstring=module_docstring(tree),
        all_exports=find_all_exports(tree),
        imports=parse_imports(tree),
        imported_atlas_modules=atlas_imports(parse_imports(tree)),
        constants=find_constants(tree),
        functions=funcs,
        classes=classes,
        issues=issues,
    )


def iter_py_files() -> List[Path]:
    files = []
    for top in INCLUDE_TOP:
        base = ROOT / top
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            if should_skip(p):
                continue
            files.append(p)
    return files


def build_reports() -> List[FileReport]:
    return [file_report(p) for p in iter_py_files()]


def layer_summary(reports: List[FileReport]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for layer in ATLAS_LAYERS:
        group = [r for r in reports if r.layer == layer]
        if not group:
            continue
        out[layer] = {
            "files": len(group),
            "functions": sum(len(r.functions) for r in group),
            "classes": sum(len(r.classes) for r in group),
            "constants": sum(len(r.constants) for r in group),
            "imports": sorted(set(i for r in group for i in r.imported_atlas_modules)),
            "modules": [r.module for r in group],
        }
    return out


def atlas_edges(reports: List[FileReport]) -> List[Dict[str, str]]:
    edges = []
    for r in reports:
        for imp in r.imported_atlas_modules:
            edges.append({"from": r.module, "to": imp})
    uniq = []
    seen = set()
    for e in edges:
        key = (e["from"], e["to"])
        if key not in seen:
            seen.add(key)
            uniq.append(e)
    return uniq


def summary_payload(reports: List[FileReport]) -> Dict[str, Any]:
    return {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "root": str(ROOT),
        "file_count": len(reports),
        "layer_summary": layer_summary(reports),
        "atlas_dependency_edges": atlas_edges(reports),
        "issues": [
            {"path": r.path, "issues": r.issues}
            for r in reports if r.issues
        ],
    }


def full_payload(reports: List[FileReport]) -> Dict[str, Any]:
    return {
        **summary_payload(reports),
        "files": [r.__dict__ for r in reports],
    }


def render_text_summary(payload: Dict[str, Any]) -> str:
    lines = []
    lines.append("ATLAS ARCH SCAN – SIGNATURE SUMMARY")
    lines.append(f"Generated: {payload['generated_at']}")
    lines.append(f"Root: {payload['root']}")
    lines.append(f"Files: {payload['file_count']}")
    lines.append("")
    lines.append("Layer summary")
    lines.append("-------------")
    for layer, info in payload["layer_summary"].items():
        lines.append(
            f"- {layer}: files={info['files']}, functions={info['functions']}, classes={info['classes']}, constants={info['constants']}"
        )
    lines.append("")
    lines.append("Atlas dependency edges")
    lines.append("----------------------")
    for e in payload["atlas_dependency_edges"]:
        lines.append(f"- {e['from']} -> {e['to']}")
    if payload["issues"]:
        lines.append("")
        lines.append("Issues")
        lines.append("------")
        for item in payload["issues"]:
            lines.append(f"- {item['path']}")
            for issue in item["issues"]:
                lines.append(f"    - {issue}")
    return "\n".join(lines) + "\n"


def render_text_full(payload: Dict[str, Any]) -> str:
    lines = [render_text_summary(summary_payload([FileReport(**f) if isinstance(f, dict) else f for f in []]))]
    lines = []
    lines.append("ATLAS ARCH SCAN – SIGNATURE INVENTORY")
    lines.append(f"Generated: {payload['generated_at']}")
    lines.append(f"Root: {payload['root']}")
    lines.append(f"Files: {payload['file_count']}")
    lines.append("")
    for layer, info in payload["layer_summary"].items():
        lines.append(f"[{layer}] files={info['files']} functions={info['functions']} classes={info['classes']} constants={info['constants']}")
    lines.append("")
    for f in payload["files"]:
        lines.append(f"=== {f['path']} ===")
        lines.append(f"layer: {f['layer']}")
        lines.append(f"module: {f['module']}")
        lines.append(f"header_ok: {f['header_ok']}")
        lines.append(f"module_docstring: {'yes' if f['module_docstring'] else 'no'}")
        if f['all_exports']:
            lines.append("__all__:")
            for x in f['all_exports']:
                lines.append(f"  - {x}")
        if f['constants']:
            lines.append("constants:")
            for x in f['constants']:
                lines.append(f"  - {x}")
        if f['imports']:
            lines.append("imports:")
            for x in f['imports']:
                lines.append(f"  - {x}")
        if f['functions']:
            lines.append("functions:")
            for x in f['functions']:
                lines.append(f"  - {x}")
        if f['classes']:
            lines.append("classes:")
            for cls in f['classes']:
                base_part = f"({', '.join(cls['bases'])})" if cls['bases'] else ""
                dc = " [dataclass]" if cls['is_dataclass'] else ""
                lines.append(f"  - class {cls['name']}{base_part}{dc}")
                if cls['fields']:
                    lines.append("    fields:")
                    for fld in cls['fields']:
                        lines.append(f"      - {fld}")
                if cls['methods']:
                    lines.append("    methods:")
                    for m in cls['methods']:
                        lines.append(f"      - {m}")
        if f['issues']:
            lines.append("issues:")
            for x in f['issues']:
                lines.append(f"  - {x}")
        lines.append("")
    return "\n".join(lines)


reports = build_reports()
payload = summary_payload(reports) if SUMMARY_ONLY else full_payload(reports)

if MODE == "--json":
    print(json.dumps(payload, indent=2, ensure_ascii=False))
else:
    if SUMMARY_ONLY:
        print(render_text_summary(payload), end="")
    else:
        print(render_text_full(payload), end="")
PYEOF

python3 "$PY_FILE" "$ROOT" "$MODE" "$SUMMARY_ONLY" > "$OUT_PATH"
echo "$OUT_PATH"
