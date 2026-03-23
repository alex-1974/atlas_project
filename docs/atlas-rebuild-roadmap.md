# Atlas — Rebuild Roadmap (v3)

> Ziel: Umbau des bestehenden Atlas auf ein neues Fundament.  
> Logik und Algorithmen bleiben erhalten. Struktur, Persistenz und CLI werden neu aufgesetzt.  
> Referenzdokumente für komplexe Themen sind verlinkt.

---

## Leitprinzipien

- **Logik bleibt.** Kein Algorithmus wird neu erfunden — nur portiert und neu strukturiert.
- **Struktur ist neu.** Ordner, Module, Namen, Datenbankschicht — alles darf umgebaut werden.
- **`.atlas/` ist der Katalog.** Analog zu `.git/`: lokal, portabel, autark.
- **`~/.atlas/` koordiniert global.** Registry aller Kataloge, geteilter Modell-Cache.
- **Zwei CLI-Bereiche.** Öffentliche Nutzer-CLI + `atlas dev` für Entwicklung und Debugging.

Siehe auch:
- [`atlas-cli-struktur.md`](./atlas-cli-struktur.md) — vollständige CLI-Referenz
- [`atlas-projektstruktur.md`](./atlas-projektstruktur.md) — Paketlayout und Modulübersicht
- [`atlas-du-pipeline.md`](./atlas-du-pipeline.md) — DU-Pipeline im Detail
- [`atlas-ontologie.md`](./atlas-ontologie.md) — Wissensgraph-Ontologie

---

## Architekturentscheidungen

Diese Entscheidungen sind getroffen und gelten für alle Phasen.

### A1 — Source of Truth: SQLite ist führend

SQLite ist die einzige Source of Truth. Der Wissensgraph (Oxigraph) ist ein Derivat — er wird aus SQLite-Daten erzeugt, nicht umgekehrt. Autoren, Titel, Identifier existieren primär in SQLite. Ein Tripel ist eine Projektion davon. Wird ein Wert in SQLite geändert, werden die betroffenen Tripel neu erzeugt. Niemals umgekehrt.

### A2 — ID-System: SHA-256 in SQL, abgeleitete URI im Graph

- `document_id` in SQLite = SHA-256 des PDF (hex, 64 Zeichen)
- `author_id` in SQLite = `sha256(normalized_name)[:16]` — kein separater UUID
- Graph-URI für Dokumente = `atlas:<sha256[:12]>`
- Graph-URI für Autoren = `atlas:author_<sha256(normalized_name)[:12]>`
- Graph-URI für Konzepte = `atlas:concept_<slug>`

Alle URI-Funktionen leben ausschließlich in `atlas/common/ids.py`. Kein anderes Modul berechnet URIs selbst.

```python
# atlas/common/ids.py
def document_uri(doc_id: str) -> str:
    return f"atlas:{doc_id[:12]}"

def author_id(normalized_name: str) -> str:
    return sha256(normalized_name.encode()).hexdigest()[:16]

def author_uri(normalized_name: str) -> str:
    return f"atlas:author_{author_id(normalized_name)[:12]}"
```

### A3 — Dokument-Identität: Datei = Dokument

SHA-256 identifiziert die Datei. Zwei PDFs derselben Arbeit sind zwei Dokumente. Gleicher DOI in zwei Dateien → als Duplikat markiert (`is_duplicate_bucket = true`), nicht als „Work mit Manifestationen". FRBR-Modellierung ist explizit ausgeschlossen.

Bei Datei-Verschiebungen oder Umbenennungen: nur `file_path` und `relative_path` werden aktualisiert — kein Remove+Add, kein Datenverlust. Dieselbe Datei zweimal im Baum → zweites Vorkommen als Duplikat markiert, nicht indexiert.

### A4 — Pipeline: Feingranulare Stages mit expliziter Invalidierung

`pipeline_stages` kennt diese finalen Stage-Namen in dieser Reihenfolge:

```
extract_text → extract_metadata → extract_identifiers → extract_authors
→ normalize_identifiers → enrich_titles → enrich_quality → enrich_ocr
→ segment → du → embedding → graph
```

Schema:
```
document_id | stage              | status  | computed_at | error
abc123      | extract_text       | done    | 2026-03-23  | null
abc123      | extract_metadata   | done    | 2026-03-23  | null
abc123      | du                 | done    | 2026-03-23  | null
abc123      | embedding          | stale   | 2026-03-23  | null
abc123      | graph              | pending | null        | null
```

Status-Werte: `pending` | `running` | `done` | `stale` | `failed`

Regeln:
- `atlas add` führt alle Stages der Reihe nach aus
- `atlas dev pipeline step <stage> <id>` berechnet eine Stage neu und setzt alle nachfolgenden auf `stale`
- `atlas update` führt nur Stages mit Status `pending` oder `stale` aus
- `atlas enrich` ist eine additive Stage außerhalb der Hauptkette — triggert keine DU-Neuberechnung, kann aber `graph` auf `stale` setzen
- Checkpoints liegen in der Datenbank, nicht in separaten Dateien
- `doc_state` in `documents` ist ein abgeleiteter Convenience-Wert: `ok` | `partial` | `failed` | `removed` — nach jeder Stage-Aktualisierung neu berechnet

### A5 — Konflikte: Prioritätskette mit Provenienz

Für jeden Metadatenwert gilt diese Priorität (höchste zuerst):

```
crossref > du > pdf_metadata > filename
```

Jeder überschreibbare Wert speichert seine Quelle:

```sql
documents.title          TEXT
documents.title_source   TEXT  -- 'crossref' | 'du' | 'pdf_metadata' | 'filename'
documents.year           INTEGER
documents.year_source    TEXT
documents.abstract       TEXT  -- klassisches wissenschaftliches Abstract, kein Summary
documents.abstract_source TEXT
```

Beim erneuten Enrichment wird nur überschrieben, wenn die neue Quelle höhere Priorität hat. `documents.abstract` enthält ausschließlich das vom Autor geschriebene Abstract — kein automatisch generiertes Summary. Quelle in Priorität: CrossRef > arXiv > DU-Extraktion (Abstract-Zone).

### A6 — text_segments vs du_blocks: verschiedene Aufgaben

Beide existieren bewusst nebeneinander:

| Tabelle | Granularität | Zweck |
|---|---|---|
| `text_segments` | grob (Absätze) | FTS5-Index, Volltextsuche |
| `du_blocks` | fein (Layout-Blöcke) | DU-Strukturanalyse |

Keine Redundanz — unterschiedliche Einheiten für unterschiedliche Aufgaben.

### A7 — Embedding-Strategie: Abstract, ein Vektor pro Dokument

Quelle: `documents.abstract` (von DU oder CrossRef befüllt, → A5).  
Fallback: erste 512 Tokens des Body aus `text_segments`.  
Ein Vektor pro Dokument in Phase 3. Chunking kommt nicht in dieser Roadmap.

### A8 — Graph-Aktualisierung: Named Graph pro Dokument, vollständiges Replace

Jedes Dokument hat einen Named Graph `atlas:graph:<doc_id[:12]>`. Bei `stale` wird dieser vollständig gelöscht und neu geschrieben. Geteilte Entitäten (Autoren, Konzepte) leben in `atlas:graph:shared` und werden nicht bei Dokumentaktualisierungen gelöscht.

### A9 — Externe Anreicherungen: primär in SQLite, dann Graph

Jede externe Quelle hat ein SQL-Ziel:

| Quelle | SQL-Ziel |
|---|---|
| CrossRef | `documents` (title, year, abstract), `authors`, `document_authors` |
| Wikidata | `document_identifiers` (type='wikidata_qid'), `authors.wikidata_id` |
| GND | `keywords` (source='gnd') |
| arXiv | `document_identifiers` (type='arxiv_id'), `documents.abstract` wenn besser |
| RVK | `documents.rvk_class`, `document_identifiers` (type='rvk') |

Graph bekommt Tripel aus diesen SQL-Daten — SQL ist immer zuerst.

### A10 — Katalogordner: rekursiv, konfigurierbar

Der Katalogordner ist der Elternordner von `.atlas/`, rekursiv. Konfigurierbar in `.atlas/config.toml`:

```toml
[index]
include = ["**/*.pdf"]
exclude = ["archive/", "tmp/"]
```

Standard ohne Konfiguration: alle PDFs rekursiv.

### A11 — `atlas dev`: registriert, in Help ausgeblendet

`atlas dev` ist als Typer-Subgruppe mit `hidden=True` im selben Entry Point registriert. Kein separater Entry Point. In Phase 6 wird `dev_app` entfernt.

```python
dev_app = typer.Typer(hidden=True)
app.add_typer(dev_app, name="dev")
```

### A12 — Autoren-Deduplizierung: normalisierter Name als Schlüssel

Normalisierung in dieser Reihenfolge: Unicode-Folding → Lowercase → Akzente entfernen → `lastname_firstname`-Reihenfolge. Der `author_id` ist `sha256(normalized_name)[:16]`. Bewusst aggressiv — zwei Schreibweisen desselben Autors sollen denselben Key erzeugen.

---

## Phase 0 — Neues Fundament

**Ziel:** Projektgerüst, SQLite-Schicht, `atlas init`.  
Noch keine Algorithmen. Nur Struktur und Konventionen.

### 0.1 Paketstruktur anlegen
- [ ] Neues `src/atlas/`-Layout gemäß [`atlas-projektstruktur.md`](./atlas-projektstruktur.md)
- [ ] `pyproject.toml` mit Entry Point `atlas`
- [ ] Abhängigkeiten definieren: `typer`, `rich`, `lancedb`, `pyoxigraph`, `sentence-transformers`, `pymupdf`, `toml`
- [ ] Virtuelle Umgebung, `pip install -e .`

### 0.2 SQLite-Verbindungsschicht
- [ ] `atlas/db/connection.py` — SQLite-Verbindung (ersetzt `psycopg`)
- [ ] `atlas/db/migrate.py` — Migration-Runner für SQLite
- [ ] Migrations-Ordner anlegen, Nummerierungsschema festlegen
- [ ] SQLite-Pragmas setzen: `foreign_keys = ON`, `journal_mode = WAL`

### 0.3 Konfigurationshierarchie
- [ ] `atlas/settings.py` — lädt: `~/.atlas/config.toml` → `.atlas/config.toml` → CLI-Flag
- [ ] Globale Defaults definieren: Embedding-Modell, Sprache, UI-Optionen, Index-Include/Exclude

### 0.4 ID-Konventionen implementieren (→ A2, A12)
- [ ] `atlas/common/ids.py` mit: `document_uri()`, `author_id()`, `author_uri()`, `concept_uri()`
- [ ] `atlas/common/normalize.py` mit: `normalize_author_name()` — Unicode-Fold, Lowercase, Lastname-First
- [ ] Einmal definiert, nie mehr geändert — alle Module importieren von hier

### 0.5 `atlas init`
- [ ] `~/.atlas/` anlegen beim ersten Aufruf: `registry.toml`, `config.toml`, `models/`
- [ ] `.atlas/` anlegen: `catalog.db`, `embeddings/`, `knowledge/`, `ontology.ttl`, `config.toml`
- [ ] `.partial`-Flag: bei Abbruch erkennen, beim nächsten `init` aufräumen
- [ ] Idempotenz: zweites `init` im selben Ordner → Fehler mit Hinweis
- [ ] Katalog in `~/.atlas/registry.toml` registrieren
- [ ] Rich-formatierter Terminal-Output

### 0.6 `atlas dev`-Bereich registrieren (→ A11)
- [ ] `dev_app = typer.Typer(hidden=True)` — im selben Entry Point, in Help unsichtbar
- [ ] `atlas dev db migrate` — Migrationen ausführen
- [ ] `atlas dev db reset` — Testdatenbank zurücksetzen (nur mit `--confirm`)
- [ ] `atlas dev schema` — aktuelles Schema anzeigen

**✓ Meilenstein:** `atlas init` läuft durch. ID-Konventionen und Normalisierung sind implementiert. Struktur steht. Katalog ist leer.

---

## Phase 1 — Basispipeline

**Ziel:** `atlas add <pdf>` indexiert ein Dokument vollständig. FTS5-Suche funktioniert. Stage-Tracking läuft.

### 1.1 SQLite-Schema: Basistabellen
- [ ] Migration: `documents`
  - `document_id TEXT PRIMARY KEY` (SHA-256, → A2)
  - `file_path`, `relative_path`, `file_name`, `file_size`, `page_count`
  - `title TEXT`, `title_source TEXT`
  - `year INTEGER`, `year_source TEXT`
  - `abstract TEXT`, `abstract_source TEXT`
  - `rvk_class TEXT`
  - `doc_state TEXT` — abgeleitet, `ok|partial|failed|removed` (→ A4)
  - `is_duplicate_bucket BOOLEAN`, `is_review_bucket BOOLEAN`
  - `created_at TEXT`
- [ ] Migration: `pipeline_stages` (→ A4)
  - `document_id`, `stage TEXT`, `status TEXT`, `computed_at TEXT`, `error TEXT`
  - Stage-Namen: `extract_text`, `extract_metadata`, `extract_identifiers`, `extract_authors`, `normalize_identifiers`, `enrich_titles`, `enrich_quality`, `enrich_ocr`, `segment`, `du`, `embedding`, `graph`
- [ ] Migration: `authors`
  - `author_id TEXT PRIMARY KEY` (sha256(normalized_name)[:16], → A2, A12)
  - `display_name TEXT`, `normalized_name TEXT`, `wikidata_id TEXT`
- [ ] Migration: `document_authors`
  - `document_id`, `author_id`, `author_position INTEGER`, `source TEXT`
- [ ] Migration: `document_identifiers`
  - `document_id`, `identifier_type TEXT`, `identifier_value TEXT`, `source TEXT`
  - Typen: `doi`, `isbn`, `arxiv_id`, `urn`, `pmid`, `wikidata_qid`, `rvk`
- [ ] Migration: `extracted_texts`
  - `document_id`, `extractor TEXT`, `text_full TEXT`, `extract_status TEXT`, `extract_error TEXT`
- [ ] Migration: `text_segments` — grobe Absätze für FTS (→ A6)
  - `document_id`, `segment_index INTEGER`, `segment_type TEXT`, `text TEXT`, `page_index INTEGER`
- [ ] Migration: `keywords`
  - `document_id`, `keyword TEXT`, `source TEXT` — `'user'|'gnd'|'extracted'`
- [ ] Migration: FTS5-Virtual-Table
  - über `documents.title`, `documents.abstract`, `text_segments.text`

### 1.2 Pipeline-Module portieren (→ A4: jedes Modul aktualisiert seine Stage)
> Logik aus bestehendem `ingest/`, `extract/`, `enrich/`, `normalize/`, `segment/`  
> portieren nach `atlas/pipeline/` — neue Struktur, gleiche Algorithmen.

- [ ] `pipeline/extract/text.py` — Stage `extract_text`: pymupdf + pdftotext-Fallback → `extracted_texts`
- [ ] `pipeline/extract/metadata.py` — Stage `extract_metadata`: PDF-Metadaten → `documents` mit `source='pdf_metadata'`
- [ ] `pipeline/extract/identifiers.py` — Stage `extract_identifiers`: DOI, ISBN, arXiv, URN, PMID → `document_identifiers`
- [ ] `pipeline/extract/authors.py` — Stage `extract_authors`: Autorenextraktion → `authors`, `document_authors`
- [ ] `pipeline/normalize/identifiers.py` — Stage `normalize_identifiers`: Normalisierung, Deduplizierung
- [ ] `pipeline/enrich/titles.py` — Stage `enrich_titles`: Titel aus Text + Dateiname → `documents` mit `source`
- [ ] `pipeline/enrich/quality.py` — Stage `enrich_quality`: Textqualitätsbewertung
- [ ] `pipeline/enrich/ocr.py` — Stage `enrich_ocr`: OCR-Kandidaten markieren
- [ ] `pipeline/segment/paragraphs.py` — Stage `segment`: Absatzsegmentierung → `text_segments`
- [ ] `pipeline/runner.py` — führt alle Stages geordnet aus, aktualisiert `pipeline_stages` und `doc_state`

### 1.3 `atlas add`
- [ ] SHA-256 berechnen, gegen `documents.document_id` prüfen (→ A3)
- [ ] Bei Duplikat: Pfad prüfen — verschoben oder echter Duplikat (→ A3)
- [ ] `pipeline/runner.py` aufrufen
- [ ] `atlas add <ordner>` — alle PDFs eines Ordners indexieren (→ A10)
- [ ] `--resume`: nur Stages mit `pending` oder `stale` ausführen (→ A4)
- [ ] Rich Progress Bar

### 1.4 `atlas update`
- [ ] Katalogordner rekursiv scannen gemäß `config.toml [index]` (→ A10)
- [ ] Neue Dateien: als neue Dokumente indexieren
- [ ] Verschobene/umbenannte Dateien: nur `file_path` aktualisieren, kein Remove+Add (→ A3)
- [ ] Verschwundene Dateien: `doc_state = 'removed'`

### 1.5 Suche & Überblick
- [ ] `atlas search "<query>"` — FTS5-Volltextsuche
- [ ] `atlas find --author / --year / --doi / --rvk` — strukturierte SQL-Abfragen
- [ ] `atlas status` — Kataloggröße, Stage-Übersicht nach Status, Schema-Version

### 1.6 `atlas dev` erweitern
- [ ] `atlas dev pipeline run <id>` — alle Stages für ein Dokument neu laufen lassen
- [ ] `atlas dev pipeline step <stage> <id>` — Einzelstage neu berechnen, Folgestages auf `stale`

**✓ Meilenstein:** Atlas ist als lokaler Katalog nutzbar. Indexierung, FTS5-Suche und feingranulares Stage-Tracking laufen.

---

## Phase 2 — Document Understanding

**Ziel:** Die vollständige DU-Pipeline läuft auf SQLite.  
Section Tree, Zonen, Dokumenttyp — alles wie bisher, auf neuem Fundament.

> Dieser Port ist der aufwändigste Schritt. Die Algorithmen bleiben vollständig erhalten.  
> Nur das Repository-Backend wird ausgetauscht: `psycopg` → SQLite.  
> Detaillierte Beschreibung der DU-Pipeline: [`atlas-du-pipeline.md`](./atlas-du-pipeline.md)

### 2.1 SQLite-Schema: DU-Tabellen
- [ ] Alle `du_*`-Tabellen neu als SQLite-Migrationen aufsetzen:
  - `du_document_context`, `du_pages`, `du_blocks`
  - `du_block_geometry`, `du_block_typography`, `du_block_surface_features`
  - `du_block_context`, `du_block_semantic_micro`, `du_block_spacing_rhythm`
  - `du_block_topology`, `du_block_topology_signals`, `du_block_page_furniture_signals`
  - `du_block_layout_features`, `du_block_signals`, `du_block_roles`
  - `du_zone_hypotheses`, `du_block_zone_memberships`, `du_semantic_zones`
  - `du_heading_candidates`, `du_section_tree`, `du_document_model`
  - DU-Typ-Spalten in `documents`: `du_document_type`, `du_document_type_confidence`
- [ ] SQLite-Constraints beachten: UUIDs als `TEXT`, Timestamps als ISO-8601, kein JSONB

### 2.2 Repository-Backend portieren
- [ ] `understanding/persistence/repository.py` — SQLite-Implementierung
- [ ] Alle `store_*`- und `fetch_*`-Methoden auf SQLite umschreiben
- [ ] Signaturen und Rückgabetypen beibehalten — kein anderer Code ändert sich
- [ ] Explizite Transaktionen (`BEGIN` / `COMMIT`) — kein Autocommit

### 2.3 DU-Module portieren
> Logik aus bestehendem `document_understanding/` portieren nach `atlas/understanding/`.

- [ ] `understanding/layers/` — alle Layer-Module (geometry, typography, surface, ...)
- [ ] `understanding/inference/` — alle Inferenz-Module (signals, roles, zones, ...)
- [ ] `understanding/layout/` — layout_graph, layout_clusters
- [ ] `understanding/segmentation/` — blocks, block_segmentation
- [ ] `understanding/core/` — Modelle, Koordinatensystem, Normalisierung
- [ ] `understanding/pipeline.py` — geordnete `compute_*`-Kette, sauber gekapselt

### 2.4 DU in `atlas add` integrieren (Stage `du`)
- [ ] `understanding/pipeline.py` als Stage `du` in `pipeline/runner.py` einhängen
- [ ] DU-Ergebnisse zurückschreiben mit Provenienz (→ A5):
  - Erkannter Titel → `documents.title` / `title_source='du'` — nur wenn Priorität erlaubt
  - Erkannte Autoren → `authors` (mit `author_id` via `ids.py`, → A2, A12), `document_authors`
  - Abstract-Block aus Zone `front` → `documents.abstract` / `abstract_source='du'` (→ A5, A7)
  - Dokumenttyp → `documents.du_document_type`
  - Referenzblöcke → bleiben in `du_block_roles`, werden in Phase 4 ausgelesen
- [ ] Stage `du` in `pipeline_stages` aktualisieren, setzt `embedding` und `graph` auf `stale`

### 2.5 `atlas inspect`
- [ ] `atlas inspect <id>` — Dokumentstruktur, Zonen, Section Tree lesbar ausgeben
- [ ] Nutzersicht: Titel, Autoren, Typ, Struktur — keine internen Layer-Werte

### 2.6 `atlas dev` erweitern
- [ ] `atlas dev du process <id>` — DU-Pipeline neu berechnen
- [ ] `atlas dev du inspect <id>` — vollständige Layer-Ansicht mit `--verbose`
- [ ] `atlas dev eval <csv>` — Evaluierung gegen Ground Truth

**✓ Meilenstein:** Atlas versteht Dokumente strukturell. Titel, Autoren und Abstract werden aus dem Dokument selbst extrahiert.

---

## Phase 3 — Semantische Suche

**Ziel:** Atlas findet Dokumente über Bedeutung, nicht nur Schlüsselwörter.

### 3.1 Embedding-Infrastruktur
- [ ] `atlas/embeddings/store.py` — LanceDB-Verbindung zu `.atlas/embeddings/`
- [ ] Schema: `document_id TEXT`, `vector`, `text_preview TEXT`
- [ ] Modell-Cache-Verwaltung: `~/.atlas/models/all-MiniLM-L6-v2/`
- [ ] Einmaliger Download beim ersten Bedarf, Offline-Prüfung

### 3.2 Embedding-Pipeline (Stage `embedding`)
- [ ] Quelle: `documents.abstract` — muss von DU befüllt sein (→ A7)
- [ ] Fallback: erste 512 Tokens aus `text_segments` (body)
- [ ] Vektor berechnen via `all-MiniLM-L6-v2`, in LanceDB schreiben
- [ ] `document_id` als Schlüssel — identisch zu SQLite (→ A2)
- [ ] Als Stage `embedding` in `pipeline/runner.py` einhängen

### 3.3 Semantische Suche
- [ ] `atlas search --semantic "<query>"` — Nearest-Neighbor via Cosine-Similarity
- [ ] `atlas similar <id>` — ähnliche Dokumente finden
- [ ] Ergebnisfusion: FTS5 + semantisch + strukturiert gemeinsam ranken

### 3.4 Clustering
- [ ] `atlas cluster` — thematische Gruppierung via k-means über Embedding-Raum

**✓ Meilenstein:** `atlas search --semantic` findet relevante Dokumente thematisch.

---

## Phase 4 — Wissensgraph

**Ziel:** Atlas versteht Beziehungen zwischen Dokumenten, Autoren und Konzepten.

> Ontologie-Definition: [`atlas-ontologie.md`](./atlas-ontologie.md)  
> Der Graph ist Derivat von SQLite (→ A1). URIs kommen ausschließlich aus `ids.py` (→ A2).  
> Named Graphs pro Dokument, vollständiges Replace bei `stale` (→ A8).

### 4.1 Oxigraph-Infrastruktur
- [ ] `atlas/knowledge/store.py` — Oxigraph-Verbindung zu `.atlas/knowledge/`
- [ ] `atlas/knowledge/triples.py` — Tripel-Erzeugung aus SQLite-Daten
- [ ] `atlas/knowledge/sparql.py` — SPARQL-Abfragen
- [ ] `ontology.ttl` beim `atlas init` laden
- [ ] Named Graph `atlas:graph:<doc_id[:12]>` pro Dokument (→ A8)
- [ ] Named Graph `atlas:graph:shared` für geteilte Entitäten (Autoren, Konzepte)

### 4.2 Tripel beim Indexieren erzeugen (Stage `graph`)
- [ ] Bei `stale`: Named Graph des Dokuments vollständig löschen und neu schreiben (→ A8)
- [ ] `authored_by`-Tripel aus `authors` / `document_authors`
- [ ] `published_in`-Tripel aus Metadaten
- [ ] `has_doi`, `has_arxiv_id`, `has_isbn`-Tripel aus `document_identifiers`
- [ ] Als Stage `graph` in `pipeline/runner.py` einhängen

### 4.3 DU → Wissensgraph
- [ ] Referenzblöcke aus `du_block_roles` auslesen (`role = 'reference'`)
- [ ] Referenztext parsen: Autor, Jahr, Titel, DOI
- [ ] `cites`-Tripel in Named Graph des Dokuments schreiben

### 4.4 SPARQL-Kommandos
- [ ] `atlas refs <id>` — Referenznetzwerk eines Dokuments
- [ ] `atlas graph --author "Name"` — Co-Autoren-Graph (DOT/JSON-Output)
- [ ] `atlas concept "Begriff"` — alle verknüpften Dokumente und Konzepte

**✓ Meilenstein:** Atlas zeigt Zitationsnetzwerke und Co-Autoren-Graphen.

---

## Phase 5 — Externe Anreicherung

**Ziel:** Atlas verbindet den lokalen Katalog mit der Wissenschaftswelt.  
Alles optional. Alles additiv. Jede Quelle schreibt zuerst in SQLite, dann in den Graph (→ A9).

### 5.1 CrossRef
- [ ] `atlas/enrich/crossref.py` — DOI → vollständige Metadaten
- [ ] Schreibt `title`, `year`, `abstract` mit `source='crossref'` — höchste Priorität (→ A5)
- [ ] Aktualisiert `authors`, `document_authors` mit `source='crossref'`
- [ ] Setzt `graph` auf `stale` (→ A4)

### 5.2 Wikidata
- [ ] `atlas/enrich/wikidata.py` — QID-Auflösung
- [ ] Schreibt `document_identifiers` (type='wikidata_qid') und `authors.wikidata_id` (→ A9)
- [ ] `owl:sameAs`-Tripel in `atlas:graph:shared`

### 5.3 GND
- [ ] `atlas/enrich/gnd.py` — kontrollierte Schlagwörter via GND-API
- [ ] Schreibt `keywords` (source='gnd') (→ A9)
- [ ] `has_gnd_keyword`-Tripel in Graph

### 5.4 arXiv
- [ ] `atlas/enrich/arxiv.py` — Metadaten via arXiv API
- [ ] Schreibt `document_identifiers` (type='arxiv_id') und ggf. `abstract` (→ A9)

### 5.5 RVK
- [ ] `atlas/enrich/rvk.py` — Klassifikation via RVK-API
- [ ] Schreibt `documents.rvk_class` und `document_identifiers` (type='rvk') (→ A9)

### 5.6 CLI
- [ ] `atlas enrich <id>` — Einzeldokument anreichern
- [ ] `atlas enrich --all` — gesamter Katalog
- [ ] Flags: `--crossref`, `--wikidata`, `--gnd`, `--arxiv`, `--rvk`

**✓ Meilenstein:** `atlas enrich` reichert den Katalog an — ohne Abhängigkeit von externen Diensten im Normalbetrieb.

---

## Phase 6 — Reife & globale Koordination

**Ziel:** Atlas ist vollständig, robust und für den Dauereinsatz bereit.

### 6.1 Globale Koordination
- [ ] `atlas global status` — alle Kataloge aus `~/.atlas/registry.toml`
- [ ] `atlas global search "<query>"` — sequenzielle Abfrage, Ergebnisse mit Herkunft
- [ ] Pfad-Validierung: fehlende oder verschobene Kataloge als `unreachable` markieren
- [ ] Kein globales Locking — jeder Katalog ist autark

### 6.2 Diagnose & Robustheit
- [ ] `atlas doctor` — prüft: fehlende PDFs (`doc_state='removed'`), Schema-Version, Modell-Cache, Stage-Inkonsistenzen, Named-Graph-Integrität
- [ ] `atlas remove <id>` — sauberes Entfernen aus SQLite, LanceDB und Oxigraph (Named Graph löschen)
- [ ] Schema-Versions-Prüfung beim Start, automatische Migration wenn möglich

### 6.3 Export
- [ ] `atlas export --bibtex`
- [ ] `atlas export --json`
- [ ] `atlas export --csv`

### 6.4 Logging & Fehlerbehandlung
- [ ] Zentrales Logging-Modul: strukturiertes Log in `.atlas/atlas.log`
- [ ] Fehlerklassen: `AtlasError`, `StageError`, `SchemaError`, `EnrichError`
- [ ] Fehlgeschlagene Stage: Details in `pipeline_stages.error`, `doc_state = 'failed'`

### 6.5 Cleanup
- [ ] `dev_app` aus `cli.py` entfernen (→ A11)
- [ ] Vollständige CLI-Referenz aktualisieren
- [ ] README neu schreiben

**✓ Meilenstein:** Atlas ist stabil, dokumentiert und für mehrere Kataloge gleichzeitig nutzbar.

---

## Abhängigkeiten auf einen Blick

```
Phase 0 — Fundament
          (ID-Konventionen, Normalisierung, SQLite, Init)
  └── Phase 1 — Basispipeline
                (12 Stages, Stage-Tracking, FTS5, atlas add/update)
        └── Phase 2 — Document Understanding
                      (DU-Port, Abstract-Extraktion, atlas inspect)
              ├── Phase 3 — Semantische Suche
              │             (LanceDB, Embeddings, atlas search --semantic)
              └── Phase 4 — Wissensgraph
                            (Oxigraph, Named Graphs, DU→cites)
                    └── Phase 5 — Externe Anreicherung
                                  (CrossRef, Wikidata, GND, RVK)
                          └── Phase 6 — Reife & globale Koordination
```

---

## Referenzdokumente

| Dokument | Inhalt |
|---|---|
| [`atlas-cli-struktur.md`](./atlas-cli-struktur.md) | Vollständige CLI-Referenz: alle Kommandos, Flags, Beispiele |
| [`atlas-projektstruktur.md`](./atlas-projektstruktur.md) | Paketlayout, Modulübersicht, Zuordnung alt → neu |
| [`atlas-du-pipeline.md`](./atlas-du-pipeline.md) | DU-Pipeline: Layer, Inferenz, Repository, process/inspect |
| [`atlas-ontologie.md`](./atlas-ontologie.md) | Wissensgraph-Ontologie: Entitäten, Beziehungen, Turtle-Schema |
