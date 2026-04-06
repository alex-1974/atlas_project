# src/atlas/understanding/eval.py
"""Ground-truth evaluation for the DU pipeline.

Compares pipeline output against manually curated CSV ground truth files
and reports precision, recall, and F1 per metric.

Ground truth files
------------------
ground_truth_documents.csv
    document_id, file_name, document_type, expected_title, expected_authors

ground_truth_sections.csv
    document_id, level, title

Usage
-----
    atlas dev eval <ground_truth_dir>

The directory must contain at least one of the two CSV files.
Results are printed to stdout. With --json, machine-readable output.
"""
from __future__ import annotations

import csv
import json
import re
from atlas.core.similarity import char_similarity as _title_sim
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path


# ── Text normalisation ────────────────────────────────────────────────────────

def _norm(text: str | None) -> str:
    """Collapse whitespace, strip, lowercase, normalize unicode.

    Maps umlauts and diacritics to ASCII equivalents so that
    ground truth written in ASCII (e.g. "In grossen Hutten") matches
    pipeline output with proper Unicode (e.g. "„In großen Hütten…“").
    """
    import unicodedata
    t = (text or "")
    # Replace ß before NFKD (NFKD maps ß→s, not ß→ss)
    t = t.replace("ß", "ss").replace("ẞ", "SS")
    # NFKD decomposition separates base characters from combining marks
    t = unicodedata.normalize("NFKD", t)
    # Drop combining characters (diacritics) — turns ü into u, ä into a etc.
    t = "".join(c for c in t if not unicodedata.combining(c))
    # Strip typographic quotes and ellipsis characters
    for ch in '„“‟”‛‘«»‹›…':
        t = t.replace(ch, "")
    return " ".join(t.split()).strip().lower()


def _norm_title(text: str | None) -> str:
    """Normalise a section title for fuzzy matching.

    Strips leading chapter numbers ("1.1 ", "IV. ") so that
    "1.1 INTRODUCTION" and "Introduction" match when compared
    after lowercasing.  The number prefix is preserved in the
    raw title and only removed for the match key.

    Also removes all whitespace before comparing — letter-spaced headings
    collapse to a single token (e.g. 'CASTLEHILL') while the ground truth
    has normal spacing ('Castle Hill'). Removing all spaces makes both
    match as 'castlehill'.
    """
    t = _norm(text)
    # Strip leading numeric prefix: "1.1 ", "3.4.6 ", "10 ", "iv ", "a.1 "
    t = re.sub(r'^(?:\d+(?:\.\d+)*|[ivx]+(?:\.\d+)?|[a-z](?:\.\d+)?)\s+', '', t)
    # Remove all remaining whitespace for whitespace-agnostic comparison
    t = t.replace(" ", "")
    return t.strip()


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class DocumentGT:
    document_id: str
    file_name: str
    document_type: str
    expected_title: str
    expected_authors: list[str]  # split on ";"


@dataclass
class SectionGT:
    document_id: str
    level: int
    title: str          # raw, with number prefix
    title_key: str      # normalised, without number prefix


@dataclass
class SectionResult:
    expected: list[SectionGT]
    found: list[str]        # titles from du_section_tree (raw)
    matched: list[str]      # expected titles that were matched
    missed: list[str]       # expected titles not found
    extra: list[str]        # found titles not in expected


@dataclass
class DocumentResult:
    document_id: str
    file_name: str
    # Document type
    expected_type: str
    actual_type: str | None
    type_correct: bool
    # Title
    expected_title: str
    actual_title: str | None
    title_correct: bool
    # Authors
    expected_authors: list[str]
    actual_authors: list[str]
    authors_found: int      # how many expected authors appear in actual
    # Section tree
    sections: SectionResult | None = None


@dataclass
class EvalReport:
    results: list[DocumentResult] = field(default_factory=list)

    # Aggregates computed by finalise()
    type_precision: float = 0.0
    title_precision: float = 0.0
    author_recall: float = 0.0
    section_precision: float = 0.0
    section_recall: float = 0.0
    section_f1: float = 0.0


# ── CSV loading ───────────────────────────────────────────────────────────────

def load_document_gt(path: Path) -> dict[str, DocumentGT]:
    result: dict[str, DocumentGT] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            did = row["document_id"].strip()
            authors_raw = row.get("expected_authors") or ""
            authors = [a.strip() for a in authors_raw.split(";") if a.strip()]
            result[did] = DocumentGT(
                document_id=did,
                file_name=row.get("file_name", "").strip(),
                document_type=row.get("document_type", "").strip(),
                expected_title=row.get("expected_title", "").strip(),
                expected_authors=authors,
            )
    return result


def load_section_gt(path: Path) -> dict[str, list[SectionGT]]:
    result: dict[str, list[SectionGT]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            did = row["document_id"].strip()
            title_raw = row.get("title", "").strip()
            entry = SectionGT(
                document_id=did,
                level=int(row.get("level", 1)),
                title=title_raw,
                title_key=_norm_title(title_raw),
            )
            result.setdefault(did, []).append(entry)
    return result


# ── DB queries ────────────────────────────────────────────────────────────────

def _fetch_document(conn: sqlite3.Connection, document_id: str) -> dict | None:
    row = conn.execute(
        """SELECT document_id, file_name, title, authors,
                  du_document_type
           FROM documents WHERE document_id = ?""",
        (document_id,),
    ).fetchone()
    return dict(row) if row else None


def _fetch_section_tree(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT level, title FROM du_section_tree
           WHERE document_id = ?
           ORDER BY start_block_index""",
        (document_id,),
    ).fetchall()]


# ── Matching logic ────────────────────────────────────────────────────────────

def _match_sections(
    expected: list[SectionGT],
    actual_rows: list[dict],
) -> SectionResult:
    """Match expected section titles against actual section tree output.

    Matching is done on normalised titles (whitespace + case + number
    prefix stripped).  Each expected title may match at most one actual
    title and vice versa (greedy left-to-right).

    The actual tree is filtered to the maximum level present in the
    ground truth.  Deeper levels beyond GT_max are excluded from the
    'extra' count.

    A level tolerance of ±1 is allowed in the title match — a GT entry
    at L3 can match a tree entry at L4 if the title matches and the tree
    entry would otherwise be filtered out.  This handles cases where the
    section tree assigns a slightly deeper level than the GT.
    """
    max_gt_level = max((gt.level for gt in expected), default=99)
    # Primary filter: entries at GT max level (for extra counting)
    filtered_rows = [r for r in actual_rows
                     if (r.get("level") or 99) <= max_gt_level]
    # Extended pool: also include one level deeper for matching only
    extended_rows = [r for r in actual_rows
                     if (r.get("level") or 99) <= max_gt_level + 1]

    actual_keys_ext   = [_norm_title(r["title"]) for r in extended_rows]
    actual_levels_ext = [r.get("level") or 99    for r in extended_rows]
    actual_raw_ext    = [r["title"]              for r in extended_rows]

    matched: list[str] = []
    missed:  list[str] = []
    used = [False] * len(actual_keys_ext)

    for gt in expected:
        found = False
        for i, (ak, al) in enumerate(zip(actual_keys_ext, actual_levels_ext)):
            if not used[i] and ak == gt.title_key and abs(al - gt.level) <= 1:
                matched.append(gt.title)
                used[i] = True
                found = True
                break
        if not found:
            missed.append(gt.title)

    # Extra = unmatched entries within the GT level range (not the extended range)
    filtered_keys = [_norm_title(r["title"]) for r in filtered_rows]
    filtered_raw  = [r["title"]              for r in filtered_rows]
    matched_keys  = {_norm_title(t) for t in matched}
    extra = [filtered_raw[i] for i, k in enumerate(filtered_keys)
             if k not in matched_keys]

    return SectionResult(
        expected=expected,
        found=[r["title"] for r in extended_rows],
        matched=matched,
        missed=missed,
        extra=extra,
    )


def _match_authors(expected: list[str], actual_json: str | None) -> tuple[list[str], int]:
    """Return (actual_authors_list, count_of_expected_found).

    Matching is fuzzy: an expected author is found if their normalised name
    appears as a substring in any normalised actual author string.
    This handles cases like:
        expected: "Heinrich Stiewe"
        actual:   "von Heinrich Stiewe, IgB"  → match
        expected: "David Pickles"
        actual:   "David Pickles and Jeremy Lake"  → match
    """
    if not actual_json:
        return [], 0
    try:
        actual = json.loads(actual_json)
        if not isinstance(actual, list):
            actual = [str(actual)]
    except (json.JSONDecodeError, TypeError):
        actual = [actual_json]

    actual_norm = [_norm(a) for a in actual]
    found = sum(
        1 for exp in expected
        if any(_norm(exp) in a_norm for a_norm in actual_norm)
    )
    return actual, found


# ── Main evaluation ───────────────────────────────────────────────────────────

def run_eval(
    conn: sqlite3.Connection,
    doc_gt: dict[str, DocumentGT],
    section_gt: dict[str, list[SectionGT]],
) -> EvalReport:
    report = EvalReport()

    all_document_ids = set(doc_gt) | set(section_gt)

    for did in sorted(all_document_ids):
        db_doc = _fetch_document(conn, did)
        if db_doc is None:
            # Document not in this catalog — skip silently
            continue

        gt = doc_gt.get(did)
        sections_expected = section_gt.get(did, [])

        # ── Title ────────────────────────────────────────────────────────
        expected_title = gt.expected_title if gt else ""
        actual_title   = db_doc.get("title") or ""
        title_correct  = bool(
            expected_title
            and (
                _norm(expected_title) == _norm(actual_title)
                or _title_sim(_norm(expected_title), _norm(actual_title)) >= 0.85
            )
        )

        # ── Authors ──────────────────────────────────────────────────────
        expected_authors = gt.expected_authors if gt else []
        actual_authors, authors_found = _match_authors(
            expected_authors, db_doc.get("authors")
        )

        # ── Document type ─────────────────────────────────────────────────
        expected_type = gt.document_type if gt else ""
        actual_type   = db_doc.get("du_document_type")
        type_correct  = bool(
            expected_type and expected_type == actual_type
        )

        # ── Section tree ─────────────────────────────────────────────────
        sections: SectionResult | None = None
        if sections_expected:
            actual_tree = _fetch_section_tree(conn, did)
            sections = _match_sections(sections_expected, actual_tree)

        report.results.append(DocumentResult(
            document_id=did,
            file_name=db_doc.get("file_name") or "",
            expected_type=expected_type,
            actual_type=actual_type,
            type_correct=type_correct,
            expected_title=expected_title,
            actual_title=actual_title,
            title_correct=title_correct,
            expected_authors=expected_authors,
            actual_authors=actual_authors,
            authors_found=authors_found,
            sections=sections,
        ))

    _finalise(report)
    return report


def _finalise(report: EvalReport) -> None:
    """Compute aggregate metrics across all document results."""
    results = report.results
    if not results:
        return

    # Type and title: simple accuracy over documents with ground truth
    type_total  = sum(1 for r in results if r.expected_type)
    type_ok     = sum(1 for r in results if r.type_correct)
    title_total = sum(1 for r in results if r.expected_title)
    title_ok    = sum(1 for r in results if r.title_correct)

    report.type_precision  = type_ok  / type_total  if type_total  else 0.0
    report.title_precision = title_ok / title_total if title_total else 0.0

    # Authors: micro-averaged recall
    exp_total  = sum(len(r.expected_authors) for r in results)
    found_total = sum(r.authors_found for r in results)
    report.author_recall = found_total / exp_total if exp_total else 0.0

    # Sections: micro-averaged precision and recall
    tp = sum(len(r.sections.matched)  for r in results if r.sections)
    fp = sum(len(r.sections.extra)    for r in results if r.sections)
    fn = sum(len(r.sections.missed)   for r in results if r.sections)

    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec  = tp / (tp + fn) if (tp + fn) else 0.0
    f1   = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0

    report.section_precision = prec
    report.section_recall    = rec
    report.section_f1        = f1


# ── Formatting ────────────────────────────────────────────────────────────────

def format_report(report: EvalReport, verbose: bool = False) -> str:
    lines: list[str] = []
    sep = "─" * 60

    for r in report.results:
        lines.append(f"\n{sep}")
        lines.append(f"  {r.file_name}  [{r.document_id[:12]}]")
        lines.append(sep)

        # Type
        if r.expected_type:
            ok = "✓" if r.type_correct else "✗"
            lines.append(f"  Type    {ok}  expected={r.expected_type!r}  "
                         f"actual={r.actual_type!r}")

        # Title
        if r.expected_title:
            ok = "✓" if r.title_correct else "✗"
            lines.append(f"  Title   {ok}  expected={r.expected_title!r}")
            if not r.title_correct:
                lines.append(f"            actual  ={r.actual_title!r}")

        # Authors
        if r.expected_authors:
            ok = "✓" if r.authors_found == len(r.expected_authors) else "~"
            lines.append(
                f"  Authors {ok}  {r.authors_found}/{len(r.expected_authors)} found"
            )
            if verbose and r.authors_found < len(r.expected_authors):
                actual_norm = {_norm(a) for a in r.actual_authors}
                for a in r.expected_authors:
                    found = "✓" if _norm(a) in actual_norm else "✗"
                    lines.append(f"            {found} {a!r}")

        # Sections
        if r.sections:
            s = r.sections
            n_exp = len(s.expected)
            n_match = len(s.matched)
            n_extra = len(s.extra)
            lines.append(
                f"  Sections  {n_match}/{n_exp} found"
                f"  +{n_extra} extra"
            )
            if verbose:
                for gt in s.expected:
                    ok = "✓" if gt.title in s.matched else "✗"
                    lines.append(f"    {ok} L{gt.level}  {gt.title!r}")
                for t in s.extra:
                    lines.append(f"    +      {t!r}")

    # ── Aggregate ─────────────────────────────────────────────────────────
    lines.append(f"\n{sep}")
    lines.append("  Aggregate")
    lines.append(sep)
    lines.append(f"  Document type accuracy  {report.type_precision:.2%}")
    lines.append(f"  Title accuracy          {report.title_precision:.2%}")
    lines.append(f"  Author recall           {report.author_recall:.2%}")
    lines.append(f"  Section precision       {report.section_precision:.2%}")
    lines.append(f"  Section recall          {report.section_recall:.2%}")
    lines.append(f"  Section F1              {report.section_f1:.2%}")
    lines.append("")

    return "\n".join(lines)


def format_report_json(report: EvalReport) -> str:
    data = {
        "aggregate": {
            "type_accuracy":       round(report.type_precision,  4),
            "title_accuracy":      round(report.title_precision, 4),
            "author_recall":       round(report.author_recall,   4),
            "section_precision":   round(report.section_precision, 4),
            "section_recall":      round(report.section_recall,    4),
            "section_f1":          round(report.section_f1,        4),
        },
        "documents": [],
    }
    for r in report.results:
        doc: dict = {
            "document_id": r.document_id,
            "file_name":   r.file_name,
            "type":        {"expected": r.expected_type, "actual": r.actual_type,
                            "correct": r.type_correct},
            "title":       {"expected": r.expected_title, "actual": r.actual_title,
                            "correct": r.title_correct},
            "authors":     {"expected": r.expected_authors, "actual": r.actual_authors,
                            "found": r.authors_found},
        }
        if r.sections:
            doc["sections"] = {
                "expected": [{"level": g.level, "title": g.title}
                             for g in r.sections.expected],
                "matched":  r.sections.matched,
                "missed":   r.sections.missed,
                "extra":    r.sections.extra,
            }
        data["documents"].append(doc)
    return json.dumps(data, ensure_ascii=False, indent=2)
