# Atlas — Embeddings & Semantische Suche

## Zweck

Die Embedding-Schicht ermöglicht semantische Ähnlichkeitssuche über
den Dokumentkorpus. Im Gegensatz zur FTS5-Volltextsuche (exakte
Wortübereinstimmung) findet `atlas similar` konzeptuell verwandte
Dokumente — auch wenn sie keine gemeinsamen Terme haben.

---

## Technologie

**LanceDB** — lokale Vektordatenbank, kein Server, kein Daemon.
Store-Pfad: `.atlas/embeddings/`. Tabelle: `paragraphs`.

**Embedding-Modell:** `all-MiniLM-L6-v2` aus `sentence-transformers`.
Dimension: 384. Einmalig heruntergeladen, dann vollständig offline.
Gecacht in `~/.atlas/models/all-MiniLM-L6-v2/`.

**Bekannte Limitation:** Das Modell ist englisch-dominant. Deutsche
Dokumente erzielen deutlich niedrigere Ähnlichkeits-Scores gegenüber
englischen Dokumenten (Stiewe DE → Edinburgh EN: 0.30 statt ~0.60).
Abhilfe in Phase 4: `paraphrase-multilingual-MiniLM-L12-v2` (OE-8).

---

## Chunk-Strategie

Nicht das gesamte Dokument wird als ein Vektor gespeichert, sondern
in semantisch kohärente Chunks zerlegt. Jeder Chunk bekommt einen
eigenen Vektor.

```
atlas add → embeddings/index.py → index_document()
    ↓
Chunk-Extraktion aus DU-Ergebnissen:
    Abstract-Block          (1 Chunk, falls vorhanden)
    Heading + Kontext        (1 Chunk pro Heading mit nachfolgendem Body)
    Body-Blöcke ≥ 40 Wörter (1 Chunk pro qualifizierender Block)
    ↓
Embedding via model.py (all-MiniLM-L6-v2)
    ↓
Speicherung in LanceDB (paragraphs-Tabelle)
```

**Warum keine Dokument-Vektoren?** Ein einzelner Vektor für ein
500-seitiges Buch würde das semantische Signal verwässern. Chunk-
Vektoren erlauben präzisere Ähnlichkeitsberechnungen.

---

## LanceDB-Schema

```python
# Tabelle: paragraphs
schema = pa.schema([
    pa.field("document_id",  pa.string()),     # SHA-256 des Dokuments
    pa.field("chunk_id",     pa.string()),     # "{document_id}_{block_index:06d}"
    pa.field("text",         pa.string()),     # Chunk-Text (max 1000 Zeichen)
    pa.field("vector",       pa.list_(pa.float32(), 384)),  # Embedding
    pa.field("page",         pa.int32()),      # Seite im Dokument
    pa.field("block_index",  pa.int32()),      # Block-Index in du_blocks
])
```

---

## Ähnlichkeitssuche: atlas similar

`atlas similar <id>` berechnet die semantische Ähnlichkeit zwischen
einem Dokument und allen anderen Dokumenten im Katalog.

**Algorithmus:**

```
1. Alle Chunk-Vektoren des Dokuments aus LanceDB lesen (to_pandas())
2. Centroid berechnen: Mittelwert aller Chunk-Vektoren, normiert
3. Vektorsuche mit Centroid als Query (limit = own_chunks + top_k × 5)
4. Ergebnisse nach Dokument aggregieren (bester Score pro Dokument)
5. Eigenes Dokument ausschließen
6. Sortieren nach Score, Top-K zurückgeben
```

**Distanz → Score:**
LanceDB gibt Cosine-Distanz zurück (0 = identisch, 2 = entgegengesetzt).
Atlas konvertiert zu Similarity: `score = max(0, 1 - dist / 2)`.

**Bekannte Tücke mit LanceDB 0.30:**
`list_tables()` gibt ein `ListTablesResponse`-Objekt zurück, keine Liste.
`table_names()` ebenfalls. Zugriff via `.tables`-Attribut:

```python
tables = db.list_tables()
existing = tables.tables if hasattr(tables, 'tables') else list(tables)
```

---

## Semantische Suche: atlas search --semantic

Noch nicht implementiert (Phase 3). Geplant: Fusion-Ranking aus
FTS5-Ergebnissen und LanceDB-Ergebnissen via Reciprocal Rank Fusion.

```
atlas search "Hallenhaus Fachwerkbau"
    ↓ FTS5 (Volltext)          ↓ LanceDB (Semantik)
    [doc_a: rank 1]            [doc_b: score 0.71]
    [doc_b: rank 2]            [doc_a: score 0.68]
    [doc_c: rank 3]            [doc_d: score 0.55]
         ↓ Fusion-Ranking (RRF)
    [doc_b: fusionScore 0.92]  ← beide Listen
    [doc_a: fusionScore 0.88]  ← beide Listen
    [doc_c: fusionScore 0.41]  ← nur FTS5
    [doc_d: fusionScore 0.38]  ← nur LanceDB
```

---

## Aktueller Stand (Testkorpus)

```
Gesamt-Chunks:    2116
  Timber Manual:  1792 Chunks  (großes Lehrbuch)
  Farm Buildings:  218 Chunks
  Edinburgh:        40 Chunks
  Stiewe (DE):      57 Chunks
  Suffolk:           9 Chunks  (kurzer Aufsatz)
```

**Ähnlichkeits-Scores:**

| Query | Bester Treffer | Score |
|---|---|---|
| Edinburgh (EN) | Farm Buildings (EN) | 0.595 |
| Timber Manual (EN) | Farm Buildings (EN) | 0.585 |
| Stiewe (DE) | Edinburgh (EN) | 0.302 |

Stiewe erzielt nur 0.27–0.30 zu englischen Dokumenten — das ist
die Sprachgrenze von `all-MiniLM-L6-v2`.

---

## Python-Integration

```python
from atlas.embeddings.store import EmbeddingStore
from atlas.embeddings.model import embed_text, get_model

# Store öffnen
store = EmbeddingStore.open(catalog_root)
print(store._table.count_rows())  # → 2116

# Ähnliche Dokumente
results = store.similar_documents(document_id, top_k=5)
# → [{"document_id": ..., "score": 0.595}, ...]

# Semantische Suche (Chunks)
results = store.search("timber frame construction", top_k=10)
# → [{"document_id": ..., "chunk_id": ..., "text": ..., "score": ...}]

# Alle Chunks eines Dokuments neu indexieren
from atlas.embeddings.index import reindex_document
n = reindex_document(conn, store, document_id)
# → Anzahl gespeicherter Chunks
```

---

## CLI-Kommandos

```bash
# Ähnliche Dokumente finden
atlas similar <id>              # Top-5 ähnliche Dokumente
atlas similar <id> --top-k 10  # Top-10

# Embeddings verwalten (dev)
atlas dev du embed-all          # Alle Dokumente neu einbetten
atlas dev du embed-all --workers 2  # Parallelisiert
```

---

## Designprinzipien

**Chunk-Granularität statt Dokument-Granularität.** Kurze Aufsätze
(Edinburgh: 40 Chunks) und lange Bücher (Timber Manual: 1792 Chunks)
sind im selben Index. Die Centroid-Berechnung gleicht unterschiedliche
Chunk-Anzahlen aus.

**Lazy Model Loading.** Das Embedding-Modell wird erst beim ersten
Aufruf geladen und dann als Singleton gehalten. `atlas status` und
andere Kommandos die keine Embeddings brauchen, laden das Modell nicht.

**Non-critical.** Wenn LanceDB nicht installiert ist oder das Modell
fehlt, läuft `atlas add` trotzdem durch — Embeddings werden
übersprungen. `atlas similar` gibt dann einen informativen Fehler.

**Idempotenz.** `reindex_document` löscht erst alle bestehenden
Chunks eines Dokuments, dann schreibt es neu. Mehrfaches Aufrufen
ist sicher.

→ Wissensgraph: [`ARCHITECTURE-KNOWLEDGE-GRAPH.md`](./ARCHITECTURE-KNOWLEDGE-GRAPH.md)
→ Datenbankschema: [`DATABASE.md`](./DATABASE.md)
