# Atlas — Implementierungs-Roadmap Phase 0 & 1

## Ziel

In kurzer Zeit ein lauffähiges Kernsystem aufbauen mit:

* `atlas init`
* `atlas add <pdf>`
* funktionierender FTS-Suche
* stabilem Pipeline- und Stage-System

**Wichtig:**
Keine neue Logik entwickeln. Bestehende Algorithmen werden später portiert.
Phase 0+1 baut ausschließlich Infrastruktur und Minimalpipeline.

---

# Phase 0 — Fundament

## Ziel

Projekt bootet stabil.
Keine Pipeline, keine Algorithmen — nur Struktur, DB und CLI.

---

## 0.1 Projektstruktur

Erzeuge das Paketlayout:

```
src/atlas/
├── cli.py
├── settings.py
├── common/
├── db/
├── catalog/
├── pipeline/
├── understanding/
├── knowledge/
├── embeddings/
├── search/
├── enrich/
├── inspect/
├── export/
└── models/
```

Siehe Referenz: Projektstruktur

---

## 0.2 pyproject.toml

```toml
[project]
name = "atlas"
dependencies = [
  "typer",
  "rich",
  "pymupdf",
  "lancedb",
  "pyoxigraph",
  "sentence-transformers",
  "toml"
]

[project.scripts]
atlas = "atlas.cli:app"
```

---

## 0.3 SQLite-Verbindung

`atlas/db/connection.py`

```python
import sqlite3
from pathlib import Path

def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn
```

---

## 0.4 Migration-System (minimal)

`atlas/db/migrate.py`

```python
def run_migrations(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY
    )
    """)
```

---

## 0.5 ID-System (kritisch)

`atlas/common/ids.py`

```python
import hashlib

def sha256_file(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

def document_uri(doc_id: str) -> str:
    return f"atlas:{doc_id[:12]}"

def author_id(normalized_name: str) -> str:
    return hashlib.sha256(normalized_name.encode()).hexdigest()[:16]
```

---

## 0.6 Normalisierung

`atlas/common/normalize.py`

```python
import unicodedata

def normalize_author_name(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower().strip()

    parts = name.split()
    if len(parts) >= 2:
        lastname = parts[-1]
        firstname = " ".join(parts[:-1])
        return f"{lastname}_{firstname}"

    return name
```

---

## 0.7 `atlas init`

Erstellt:

```
.atlas/
├── catalog.db
├── embeddings/
├── knowledge/
├── config.toml
```

Zusätzlich:

```
~/.atlas/
├── registry.toml
├── config.toml
└── models/
```

---

## 0.8 CLI-Grundgerüst

`atlas/cli.py`

```python
import typer

app = typer.Typer()
dev_app = typer.Typer(hidden=True)

app.add_typer(dev_app, name="dev")

@app.command()
def init():
    ...
```

---

## Phase-0-Abnahme

Fertig, wenn:

* `atlas init` funktioniert
* `.atlas/` korrekt erzeugt wird
* SQLite verbunden ist
* CLI stabil startet

---

# Phase 1 — Basispipeline

## Ziel

Ein Dokument kann vollständig indexiert werden.

---

## 1.1 Datenbankschema

Minimal starten:

```sql
CREATE TABLE documents (
    document_id TEXT PRIMARY KEY,
    file_path TEXT,
    title TEXT,
    title_source TEXT,
    abstract TEXT,
    abstract_source TEXT,
    doc_state TEXT,
    created_at TEXT
);

CREATE TABLE pipeline_stages (
    document_id TEXT,
    stage TEXT,
    status TEXT,
    computed_at TEXT,
    error TEXT,
    PRIMARY KEY (document_id, stage)
);

CREATE TABLE extracted_texts (
    document_id TEXT,
    text_full TEXT
);

CREATE TABLE text_segments (
    document_id TEXT,
    segment_index INTEGER,
    text TEXT
);
```

---

## 1.2 Stage-System

Definiere feste Reihenfolge:

```python
STAGES = [
    "extract_text",
    "extract_metadata",
    "extract_identifiers",
    "extract_authors",
    "normalize_identifiers",
    "enrich_titles",
    "enrich_quality",
    "enrich_ocr",
    "segment",
]
```

---

## 1.3 Stage-Tracking

```python
def set_stage(conn, doc_id, stage, status):
    conn.execute("""
        INSERT OR REPLACE INTO pipeline_stages
        (document_id, stage, status)
        VALUES (?, ?, ?)
    """, (doc_id, stage, status))
```

---

## 1.4 Invalidation

```python
def invalidate_following(conn, doc_id, stage):
    idx = STAGES.index(stage)
    for s in STAGES[idx+1:]:
        set_stage(conn, doc_id, s, "stale")
```

---

## 1.5 Pipeline Runner

```python
def run_pipeline(conn, doc_id, file_path):
    run_extract_text(...)
    run_extract_metadata(...)
    run_segment(...)
```

Regel:

* jede Stage ist isoliert
* keine Seiteneffekte außerhalb eigener Tabellen

---

## 1.6 Textextraktion

```python
import fitz

def extract_text(file_path):
    doc = fitz.open(file_path)
    return "\n".join(page.get_text() for page in doc)
```

---

## 1.7 Segmentierung

```python
def segment_text(text):
    return text.split("\n\n")
```

---

## 1.8 `atlas add`

```python
def add(file_path):
    doc_id = sha256_file(file_path)

    if exists(doc_id):
        return

    insert_document(doc_id)

    run_pipeline(...)
```

---

## 1.9 `atlas update`

* scannt rekursiv
* neue Dateien → indexieren
* fehlende Dateien → `doc_state = 'removed'`

---

## 1.10 FTS5-Suche

```sql
CREATE VIRTUAL TABLE fts USING fts5(
    title,
    abstract,
    text
);
```

---

```python
def search(query):
    SELECT * FROM fts WHERE fts MATCH ?
```

---

## 1.11 doc_state

```python
def compute_doc_state(stages):
    if any(s == "failed"):
        return "failed"
    if all(s == "done"):
        return "ok"
    return "partial"
```

---

## 1.12 CLI

```bash
atlas add file.pdf
atlas search "query"
atlas status
```

---

## Phase-1-Abnahme

Fertig, wenn:

* Dokumente indexiert werden
* Text extrahiert ist
* Segmente vorhanden sind
* Stage-Tracking funktioniert
* Suche Ergebnisse liefert

---

# Empfohlene Reihenfolge

1. Phase 0 komplett
2. DB-Schema
3. Stage-System
4. extract_text
5. atlas add
6. Segmentierung
7. Suche
8. restliche Stages stubben

---

# Ergebnis nach Phase 1

Du hast:

* funktionierenden lokalen Literaturkatalog
* stabile Pipeline-Architektur
* deterministische IDs
* Grundlage für DU, Embeddings und Wissensgraph

---

