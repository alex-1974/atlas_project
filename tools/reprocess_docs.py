#!/usr/bin/env python3
"""
Verarbeitet bestehende Dokumente neu durch parse_document + save_parse_result.
Nützlich nach Fixes an metadata.py (z.B. DOI-Regex).

Usage:
    python scripts/reprocess_docs.py                    # alle Dokumente
    python scripts/reprocess_docs.py --pattern "Tree_Ring"  # gefiltert
"""
import sys, sqlite3, glob, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from atlas.parse.pipeline import parse_document
from atlas.parse.repository import save_parse_result
from atlas.db.connection import connect
from atlas.pipeline.runner import _update_fts

parser = argparse.ArgumentParser()
parser.add_argument("--pattern", default="", help="Dateinamen-Filter")
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()

import os
# Nutze aktuelles Verzeichnis als Katalogwurzel (wie atlas selbst)
catalog_root = Path(os.getcwd())
db_path = catalog_root / ".atlas" / "catalog.db"
if not db_path.exists():
    # Fallback: suche in bekannten Pfaden
    dbs = glob.glob(str(Path.home() / "**/.atlas/catalog.db"), recursive=True)
    if not dbs:
        print("Kein Katalog gefunden — bitte ins Katalogverzeichnis wechseln")
        sys.exit(1)
    db_path = Path(dbs[0])
print(f"Katalog: {db_path.parent.parent}")
conn = connect(db_path)

query = "SELECT document_id, file_path, title, doi FROM documents"
if args.pattern:
    query += f" WHERE file_path LIKE '%{args.pattern}%'"

rows = conn.execute(query).fetchall()
print(f"Verarbeite {len(rows)} Dokument(e)"
      + (f" (Filter: {args.pattern!r})" if args.pattern else ""))

for row in rows:
    doc_id   = row["document_id"]
    pdf_path = Path(row["file_path"])
    print(f"\n  {pdf_path.name}")
    print(f"  Vor:  doi={row['doi']!r}  title={str(row['title'])[:40]!r}")

    if args.dry_run:
        continue

    if not pdf_path.exists():
        print(f"  FEHLER: Datei nicht gefunden")
        continue

    parsed = parse_document(pdf_path)
    if not parsed.pipeline_ok:
        print(f"  FEHLER: {parsed.error}")
        continue

    save_parse_result(conn, doc_id, parsed)
    _update_fts(conn, doc_id, parsed=parsed)

    after = conn.execute(
        "SELECT doi, title FROM documents WHERE document_id=?", (doc_id,)
    ).fetchone()
    print(f"  Nach: doi={after['doi']!r}  title={str(after['title'])[:40]!r}")

conn.close()
print("\nFertig.")
