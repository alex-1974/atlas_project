# Atlas — Roadmap

## Entwicklungsphasen

### Phase 1 — Fundament ✓ abgeschlossen März 2026

**Erreichte Qualitätsziele (Testkorpus 5 Dokumente):**

| Metrik | Ziel | Erreicht |
|---|---|---|
| Dokumenttyp-Genauigkeit | — | **100%** |
| Titel-Extraktion | 90% | **100%** |
| Autoren-Extraktion | 80% | 57% |
| Section-Tree F1 | — | 54% |

**Bekannte Lücken:**
- Autoren im Fließtext und Institutionen als Autoren nicht erkannt
- Letter-spaced Headings in mehrspaltigen Layouts: strukturelles Limit
  ohne `column_hint` (→ Phase 4)

---

### Phase 2 — Verknüpfung & Suche ✓ abgeschlossen April 2026

**Geliefert:**
- LanceDB-Integration (`atlas similar`) — 2116 Chunks, 5 Dokumente
- Oxigraph-Wissensgraph (`atlas refs`, `atlas graph`) — 658 Tripel
- Keywords (YAKE, zweistufig mit KeyBERT als Option)
- Themenextraktion (`atlas enrich --themes`)
- Identifier-Resolution: `enrich/wikidata.py`, `enrich/crossref.py`,
  `enrich/orcid.py`, `enrich/rvk.py`
- `atlas find`, `atlas concept`, `atlas enrich` CLI vollständig
- Migrationen 0012 (keywords, document_identifiers), 0013 (subjects)

**Bekannte Lücken:**
- `all-MiniLM-L6-v2` englisch-dominant: deutsche Dokumente haben
  niedrige Ähnlichkeits-Scores zu englischen (Stiewe: 0.27–0.30)
- Wikidata/CrossRef/ORCID: implementiert, brauchen Netz (nicht getestet)
- Referenz-Parser für `cites`-Tripel: DOI-Extraktion vorhanden,
  vollständiger Parser fehlt noch
- `atlas search --semantic` (Fusion-Ranking FTS5 + LanceDB) fehlt noch

**Abschluss-Kriterium:** `atlas similar` liefert sinnvolle Ergebnisse
für englische Dokumente. Wissensgraph hat lokale Tripel für alle
Dokumente. Keywords werden automatisch beim `atlas add` extrahiert.

---

### Phase 3 — Anreicherung & Export

**Ziel:** Tiefere externe Anreicherung, kontrolliertes Vokabular,
Exportformate.

**Enthält:**
- GND-Integration (`atlas enrich --gnd`)
- RVK-Vertiefung: vollständige Klassifikationshierarchie
- Wikidata-Reconciliation für Konzepte
- Referenz-Parser: Referenzblöcke → strukturierte `cites`-Tripel
- Fusion-Ranking: FTS5 + LanceDB kombiniert (`atlas search --semantic`)
- BibTeX, JSON, CSV Export
- `atlas global status` und `atlas global search`
- Deduplizierung bei mehreren Katalogen (OE-4)

---

### Phase 4 — Reife & Produktivität

**Ziel:** Tägliche Nutzung ohne Reibungsverluste, strukturelle Lücken
aus Phase 1 und 2 schließen.

**Enthält:**
- Spaltenerkennung (`column_hint`) — schließt Edinburgh-Limit
- Mehrsprachige Embeddings: `paraphrase-multilingual-MiniLM-L12-v2`
  als Alternative zu `all-MiniLM-L6-v2` für DE/FR/NL-Dokumente
- Autoren-Extraktion aus Fließtext
- Inkrementelles Update
- Performance-Optimierung (LanceDB ANN-Index für >1000 Dokumente)
- Verbesserte OCR-Pipeline
- i18n-Ordner
- `atlas dev` auslagern

---

## Offene Entscheidungen

### OE-1: Spaltenerkennung
**Status:** Zurückgestellt auf Phase 4.

### OE-2: Autoren-Extraktion
**Status:** Basis in Phase 1. ORCID-Disambiguierung in Phase 2
implementiert (braucht Netz). Vollständige Lösung Phase 4.

### OE-3: Dokumenttyp-Klassifikation ✓
**Status:** Abgeschlossen in Phase 1. 100% auf Testkorpus.

### OE-4: Konfliktauflösung bei mehreren Katalogen
**Status:** Relevant ab Phase 3.

### OE-5: Persistenz der DU-Zwischenergebnisse
**Status:** Option A (alle Layer persistent). Bewertung Phase 4.

### OE-6: i18n-Architektur
**Status:** Hardcoded Sets in Phase 1. YAML-basiert in Phase 4.

### OE-7: Wikidata als Verbindungsknoten ✓
**Status:** Implementiert in Phase 2 (`enrich/wikidata.py`).
Produktiver Einsatz sobald Netzwerkzugang verfügbar.

### OE-8: Mehrsprachige Embeddings

`all-MiniLM-L6-v2` ist englisch-dominant. Deutsche Dokumente
(Stiewe) haben Ähnlichkeits-Scores von 0.27–0.30 zu englischen
Dokumenten — semantisch korrekt, aber für einen mehrsprachigen
Katalog unbefriedigend.

**Optionen:**
- A) `paraphrase-multilingual-MiniLM-L12-v2` — gleiche Dimension
  (384), direkt austauschbar, gute EN/DE/FR-Performance
- B) Sprach-spezifische Embedding-Modelle pro Dokument — komplex
- C) Übersetzungs-Pipeline vor Embedding — aufwendig, verlustbehaftet

**Status:** Option A empfohlen für Phase 4. Modellwechsel erfordert
`atlas dev du embed-all` (alle Embeddings neu berechnen).

---

## Bekannte Einschränkungen

**Nicht unterstützt:**
- Passwortgeschützte PDFs
- PDFs mit ausschließlich Vektorgrafiken ohne Text
- Rechts-nach-Links-Sprachen
- Sehr große PDFs (>500 Seiten) — langsam

**Bekannte Schwächen:**
- Mehrspaltige Layouts: `body_like`-Scores ohne `column_hint`
- Letter-spaced Headings in Spalten-Kontext
- Tabelleninhalte: nicht als strukturierte Tabellen extrahiert
- Mathematische Formeln: als Body-Text behandelt
- Mehrsprachige Ähnlichkeitssuche: englisch-dominant (OE-8)

---

## Qualitätsziele

| Metrik | Phase 1 | Phase 2 | Ziel Phase 4 |
|---|---|---|---|
| Dokumenttyp-Genauigkeit | **100%** | **100%** | 100% |
| Titel-Extraktion | **100%** | **100%** | 100% |
| Autoren-Extraktion | 57% | 57% | 90% |
| Section-Tree F1 | 54% | 54% | 0.80 |
| Identifier-Auflösungsrate (DOI→QID) | — | impl. | 85% |
| Semantische Ähnlichkeit (EN→EN) | — | **0.595** | 0.70 |
| Verarbeitungszeit pro Dokument | <10s | <15s | <10s |
