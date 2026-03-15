#!/usr/bin/env python3
"""Build a simple Atlas pipeline map from README and optional CLI source.

Default Atlas layout:
    atlas_project/tools/pipeline_map.py
    atlas_project/README.md
    atlas_project/src/atlas/cli.py
    atlas_project/generated/pipeline.md

Optional usage:
    python tools/pipeline_map.py
    python tools/pipeline_map.py --root . --out generated/pipeline.md
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

PIPELINE_FALLBACK = [
    "discover",
    "register",
    "extract-text",
    "extract-metadata",
    "extract-identifiers",
    "normalize-identifiers",
    "dedupe-identifiers",
    "enrich-title-text",
    "enrich-title-filename",
    "enrich-quality",
    "mark-ocr-candidates",
    "segment-paragraphs",
    "search",
]

CLI_PATTERNS = [
    re.compile(r'@app\.command\((?:name\s*=\s*)?["\']([^"\']+)["\']'),
    re.compile(r'add_command\([^,]+,\s*["\']([^"\']+)["\']\)'),
    re.compile(r'["\']([a-z0-9\-]+)["\']\s*:\s*[a-zA-Z_][\w]*'),
]


def extract_commands_from_cli(cli_text: str) -> list[str]:
    commands: set[str] = set()
    for pattern in CLI_PATTERNS:
        for match in pattern.finditer(cli_text):
            commands.add(match.group(1))
    return sorted(commands)


def extract_pipeline_from_readme(readme_text: str) -> list[str]:
    lines = [line.strip() for line in readme_text.splitlines()]
    steps: list[str] = []
    capture = False
    for line in lines:
        if line.lower().startswith("# typical workflow") or line.lower().startswith("# architecture"):
            capture = True
            continue
        if capture and line.startswith("#") and not line.lower().startswith("# typical workflow") and not line.lower().startswith("# architecture"):
            capture = False
        if capture:
            if line in {"↓", "->", ""}:
                continue
            if re.fullmatch(r"[a-z][a-z0-9\-]+", line):
                steps.append(line)
            elif line.startswith("atlas "):
                steps.append(line.removeprefix("atlas ").strip())
    deduped: list[str] = []
    seen: set[str] = set()
    for step in steps:
        if step not in seen:
            deduped.append(step)
            seen.add(step)
    return deduped


def build_report(root: Path) -> str:
    readme = root / "README.md"
    cli = root / "src" / "atlas" / "cli.py"

    readme_steps = extract_pipeline_from_readme(readme.read_text(encoding="utf-8")) if readme.exists() else []
    cli_cmds = extract_commands_from_cli(cli.read_text(encoding="utf-8")) if cli.exists() else []
    steps = readme_steps or PIPELINE_FALLBACK

    out: list[str] = ["# Pipeline Map", ""]
    out += ["## Ordered Flow", ""]
    for i, step in enumerate(steps, start=1):
        out.append(f"{i}. `{step}`")
    out += ["", "## Mermaid", "", "```mermaid", "flowchart TD"]
    for idx, step in enumerate(steps):
        safe = step.replace("-", "_")
        out.append(f'    {safe}["{step}"]')
        if idx > 0:
            prev = steps[idx - 1].replace("-", "_")
            out.append(f"    {prev} --> {safe}")
    out += ["```", ""]

    out += ["## CLI Commands Found", ""]
    if cli_cmds:
        for cmd in cli_cmds:
            out.append(f"- `{cmd}`")
    else:
        out.append("- no CLI commands detected heuristically")
    out.append("")

    out += ["## Notes", ""]
    out.append("- Readme-derived flow is usually the best high-level onboarding path.")
    out.append("- CLI-derived commands are useful to compare intended vs exposed workflow.")
    out.append("- For Document Understanding, add a second pipeline branch once `segment-regions` and related commands exist.")
    return "\n".join(out)


def main() -> None:
    script_path = Path(__file__).resolve()
    default_root = script_path.parents[1]

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(default_root))
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_path = Path(args.out).resolve() if args.out else (root / "generated" / "pipeline.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    out_path.write_text(build_report(root), encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
