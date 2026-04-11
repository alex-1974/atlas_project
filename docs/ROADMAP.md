# Atlas — Roadmap

## Entwicklungsphasen

### Phase 1 — Fundament ✓ abgeschlossen März 2026

**Ziel:** Stabiler, lokaler Katalog mit vollständiger DU-Pipeline
auf SQLite-Basis.

**Geliefert:**
- Vollständiger Rebuild von `understanding/` mit neuer Drei-Schichten-Architektur
- Migration von PostgreSQL auf SQLite
- `core/vocab.py` und `core/text_patterns.py` als gemeinsame Grundlagen
- Konsolidierung der fünf Zonierungssysteme auf zwei
- `atlas init`, `atlas add`, `atlas remove`, `atlas update`
- `atlas search` (Volltext via FTS5)
- `atlas dev du process/inspect/eval`
- `atlas status`, `atlas inspect`, `atlas doctor`

**Erreichte Qualität (Testkorpus 5 Dokumente):**

| Metrik | Ziel | Erreicht |
|---|---|---|
| Dokumenttyp-Genauigkeit | — | 100% |
| Titel-Extraktion | 90% | 100% |
| Autoren-Extraktion | 80% | 57% |
| Section-Tree F1 | — | 54% |

---

### Phase 2 — Verknüpfung & Erschließung ✓ abgeschlossen April 2026

**Ziel:** Semantische Suche, Wissensgraph und bibliografische
Erschließung als vollständig nutzbare Features.

**Geliefert:**
- LanceDB-Integration (2116 Chunks, `atlas similar`)
- Oxigraph-Wissensgraph (658 Tripel, `atlas refs`, `atlas graph`, `atlas concept`)
- `atlas find` mit strukturierten Filtern
- Keyword-Extraktion via YAKE (`atlas enrich --keywords`)
- Topic-Extraktion via GND-Normalisierung (`atlas enrich --topic`)
- Section-Keywords via YAKE pro Kapitel (`atlas enrich --section-keywords`)
- GND-Anreicherung via lobid.org (`atlas enrich --gnd`)
- RVK-Klassifikation via rvk.uni-regensburg.de (`atlas enrich --rvk`)
- Wikidata-, CrossRef-, ORCID-Integration (implementiert, braucht Netz)
- Migrationen 0012–0014
- Strukturiertes Logging (`atlas.core.logging`, `ATLAS_LOG`-Umgebungsvariable)
- DU-Pipeline-Fixes: OCR-Klassifikation, Zonengrenzen, `_detect_title`-Fallback

**Bekannte Lücken:**
- `all-MiniLM-L6-v2` englisch-dominant (Stiewe: 0.27–0.30)
- Keyword-Qualität begrenzt RVK-Treffsicherheit
- `atlas search --semantic` fehlt noch
- Referenz-Parser für `cites`-Tripel fehlt noch

**Erreichte Qualität (Testkorpus 21 Dokumente, April 2026):**

| Metrik | Phase 1 | Phase 2 |
|---|---|---|
| Dokumenttyp-Genauigkeit | 100% | 85% |
| Titel-Extraktion | 100% | 25% |
| Autoren-Extraktion | 57% | 32% |
| Section-Tree Precision | — | 13% |
| Section-Tree Recall | — | 77% |
| Section-Tree F1 | 54% | 23% |

Hinweis: Phase-1-Zahlen basieren auf 5 Dokumenten, Phase-2-Zahlen
auf 21 Dokumenten — direkter Vergleich nur eingeschränkt aussagekräftig.

---

### Phase 3 — DU-Rewrite & Qualität (laufend)

**Ziel:** Dokumentverständnis auf solides Fundament stellen.
Opportunistisch statt erzwingend: hochkonfidente Strukturerkennung
wenn das Dokument es hergibt, robuste Basisextraktion wenn nicht.

**Leitprinzip:** Atlas versucht nicht, jedes Dokument vollständig zu
verstehen. Ohne erkennbares Heading-Pattern bleibt der Section Tree
leer — das ist korrekt. Reine Fließtexte werden als solche erkannt.

**P1 — Titel-Extraktion reparieren (25% → 80%+)**
Der wichtigste einzelne Qualitätswert. Direkte Auswirkung auf
Katalognutzbarkeit.

**P2 — DU-Pipeline dokumentrelativ machen**
Neuer Ansatz: TypographyProfile + Anchor Detection + HeadingPattern.
Absolute Schwellenwerte werden durch dokumentrelative Messungen ersetzt.
Details → `ARCHITECTURE-DU-PIPELINE.md`.

**P3 — Noise-Filter verbessern**
Running Headers, Seitenzahlen, Formelblöcke, Captions sauber aus dem
Body heraushalten. Direkter Impact auf Keywords, FTS und Embeddings.

**P4 — Export & Suche**
- `atlas search --semantic` — Fusion-Ranking FTS5 + LanceDB
- Referenz-Parser: Referenzblöcke → `cites`-Tripel
- BibTeX, JSON, CSV Export (`atlas export`)
- `atlas global status` und `atlas global search`

**P5 — Erschließungsqualität**
- MultipartiteRank (pke) als Alternative zu YAKE
- RVK-Qualität: Topic als primäre Suchanfrage
- GND: `broaderTermInstantial` für Topic-Hierarchie

---

### Phase 4 — Reife & Produktivität

**Ziel:** Tägliche Nutzung ohne Reibungsverluste.

**Enthält:**
- Mehrsprachige Embeddings: `paraphrase-multilingual-MiniLM-L12-v2`
- Autoren-Extraktion verbessern
- Inkrementelles Update
- Performance-Optimierung: LanceDB ANN-Index für >1000 Dokumente
- Verbesserte OCR-Pipeline für Archivdokumente
- i18n: Section-Labels in `core/i18n/`
- `atlas dev` auslagern oder entfernen
- Altes `src/atlas/document_understanding/` entfernen

---

## Offene Entscheidungen

### OE-1: Spaltenerkennung

`column_hint` ist im Schema vorhanden aber nie befüllt.
Im neuen Ansatz teilweise durch `TypographyProfile` adressiert
(body_font nach Zeichenanzahl ist spaltenunabhängig).

**Status:** Zurückgestellt auf Phase 4.

---

### OE-2: Autoren-Extraktion

`author_like` erkennt Institutionen und mehrteilige Namen nicht zuverlässig.

**Status:** Grundfunktion in Phase 1. Verbesserung in Phase 4.

---

### OE-3: Dokumenttyp-Klassifikation ✓

Regelbasiert über `early_meta`-Signale implementiert.
100% auf 5 Dokumenten, 85% auf 21 Dokumenten.

---

### OE-4: Konfliktauflösung bei mehreren Katalogen

**Status:** Offen. Relevant ab Phase 3 (`atlas global search`).

---

### OE-5: Persistenz der DU-Zwischenergebnisse

Im neuen Ansatz kommen `TypographyProfile`-Felder in `du_documents`
und `du_heading_patterns` als neue Tabelle hinzu.

**Status:** Schema-Entscheidung in Phase 3.

---

### OE-6: i18n-Architektur

Section-Labels hartcodiert in `text_patterns.py` und `section_labels.py`.

**Status:** Zurückgestellt auf Phase 4.

---

### OE-7: Wikidata als Verbindungsknoten ✓

`enrich/wikidata.py` implementiert.

---

### OE-8: Mehrsprachige Embeddings

`all-MiniLM-L6-v2` englisch-dominant. DE-Dokumente: 0.27–0.30.
Option A: `paraphrase-multilingual-MiniLM-L12-v2` empfohlen für Phase 4.

---

### OE-9: Keyword-Qualität für Sacherschließung

YAKE produziert zu unspezifische Terme für RVK/GND-Klassifikation.
MultipartiteRank (pke) als Alternative in Phase 3 (P5).

---

### OE-10: DU-Opportunismus (neu)

Das neue DU-System folgt dem Prinzip: strukturierte Erkennung nur
wenn hochkonfident, nie raten.

Konkrete Konsequenzen:
- Kein erkennbares Heading-Pattern → leerer Section Tree
- Schwache Struktur → nur L1 wenn konfident
- Tiefe Hierarchie (L4+) → nur bei nummerierter Gliederung oder TOC

**Status:** Leitprinzip für Phase 3.

---

## Bekannte Einschränkungen

**Nicht unterstützt:**
- Passwortgeschützte PDFs
- PDFs ohne Text-Layer
- Rechts-nach-Links-Sprachen
- Sehr große PDFs (>500 Seiten) — langsam
- Dokumente mit inkonsistenter Heading-Formatierung

**Bekannte Schwächen der DU-Pipeline (Phase 2):**
- Titel-Extraktion 25% — wichtigstes offenes Problem
- Section Precision 13% — Formelblöcke, TOC-Duplikate als Headings
- Laudel Dissertation: 0/8 Sections (Zonierungsproblem)
- Absolute Schwellenwerte → wird durch TypographyProfile adressiert

**Bekannte Schwächen der Erschließung:**
- Mehrsprachige Ähnlichkeitssuche englisch-dominant (OE-8)
- RVK-Treffsicherheit abhängig von Keyword-Qualität
- GND: Personen und Körperschaften ohne Typ-Filter

---

## Qualitätsziele

| Metrik | Phase 2 | Ziel Phase 3 | Ziel Phase 4 |
|---|---|---|---|
| Dokumenttyp-Genauigkeit | 85% | 90% | 95% |
| Titel-Extraktion | 25% | 80% | 90% |
| Autoren-Extraktion | 32% | 50% | 80% |
| Section-Tree Precision | 13% | 60% | 75% |
| Section-Tree Recall | 77% | 75% | 85% |
| Section-Tree F1 | 23% | 67% | 80% |
| Semantische Ähnlichkeit EN→EN | 0.595 | 0.65 | 0.70 |
| Semantische Ähnlichkeit DE→EN | 0.30 | 0.35 | 0.55 |
| Topic-Qualität | 60% | 70% | 85% |
| RVK-Treffsicherheit | ~20% | 40% | 70% |
| Verarbeitungszeit/Dokument | <15s | <12s | <10s |
