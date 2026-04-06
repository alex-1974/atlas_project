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
  Input auf Titel + Abstract + Seiten 0–2 beschränkt
- Topic-Extraktion via GND-Normalisierung (`atlas enrich --topic`)
  Pipeline: GND-IDs → lobid.org preferred label → Keyword-Fallback
- Section-Keywords via YAKE pro Kapitel (`atlas enrich --section-keywords`)
- GND-Anreicherung via lobid.org (`atlas enrich --gnd`)
- RVK-Klassifikation via rvk.uni-regensburg.de (`atlas enrich --rvk`)
- Wikidata-, CrossRef-, ORCID-Integration (implementiert, braucht Netz)
- Migrationen 0012–0014 (keywords, subjects, topic, document_identifiers,
  du_section_keywords)
- Strukturiertes Logging (`atlas.core.logging`, `ATLAS_LOG`-Umgebungsvariable)
- DU-Pipeline-Fixes: OCR-Klassifikation, Zonengrenzen, nummerierte Headings

**Bekannte Lücken:**
- `all-MiniLM-L6-v2` englisch-dominant: deutsche Dokumente haben
  niedrige Ähnlichkeits-Scores (Stiewe: 0.27–0.30)
- Keyword-Qualität begrenzt RVK-Treffsicherheit
- `atlas search --semantic` (Fusion FTS5 + LanceDB) fehlt noch
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

Hinweis: Phase-1-Zahlen basieren auf 5 Dokumenten, Phase-2-Zahlen auf
21 Dokumenten mit erweitertem Ground-Truth-Korpus — direkte Vergleiche
sind daher nur eingeschränkt aussagekräftig.

---

### Phase 3 — Export & Qualität

**Ziel:** Exportformate, Fusion-Suche, bessere Erschließungsqualität.

**Enthält:**
- `atlas search --semantic` — Fusion-Ranking FTS5 + LanceDB
- Referenz-Parser: Referenzblöcke → strukturierte `cites`-Tripel
- BibTeX, JSON, CSV Export (`atlas export`)
- `atlas global status` und `atlas global search`
- GND-Anreicherung vertiefen: `broaderTermInstantial` für Topic-Hierarchie
- Keyword-Qualität: MultipartiteRank (pke) als Alternative zu YAKE
- Thesaurus-Boost: GND-Kandidaten in YAKE-Kandidaten höher gewichten
- RVK-Qualität: Topic als primäre Suchanfrage statt YAKE-Keywords
- Section precision verbessern: Formelblöcke (`Given:`, `Solution:`, `Answer:`)
  werden fälschlich als Headings erkannt (Timber Manual: +228 extras)
- Title accuracy verbessern: viele Dokumente ohne erkannten Titel (`actual=''`)
- Laudel Dissertation: 0/8 Sections gefunden (Zonierungsproblem)
- `runner.py`: Pass-0 DocumentProfile vollständig integrieren

---

### Phase 4 — Reife & Produktivität

**Ziel:** Tägliche Nutzung ohne Reibungsverluste, strukturelle
Lücken aus Phase 1 und 2 schließen.

**Enthält:**
- Spaltenerkennung (`column_hint`) — schließt Edinburgh-Limit
  bei letter-spaced Headings in Mehrspaltenlayouts
- Mehrsprachige Embeddings: `paraphrase-multilingual-MiniLM-L12-v2`
  als Alternative zu `all-MiniLM-L6-v2` für DE/FR/NL-Dokumente
- Autoren-Extraktion aus Fließtext verbessern
- Inkrementelles Update (nur geänderte Dokumente neu verarbeiten)
- Performance-Optimierung: LanceDB ANN-Index für >1000 Dokumente
- Verbesserte OCR-Pipeline für Archivdokumente
- `atlas dev` auslagern oder entfernen
- i18n: Section-Labels in `core/i18n/` statt hartkodierten Sets
- Altes `src/atlas/document_understanding/` Verzeichnis entfernen

---

## Offene Entscheidungen

### OE-1: Spaltenerkennung

`column_hint` ist im Schema vorhanden aber nie befüllt.
Echte Spaltenerkennung würde `body_like`-Scores verbessern
und das Edinburgh-Limit bei letter-spaced Headings lösen.

**Optionen:**
- A) Clustering der x0-Positionen pro Seite (einfach, robust)
- B) Layout-Graph-Ansatz wie im alten `layout_clusters.py` (mächtiger, komplexer)

**Status:** Zurückgestellt auf Phase 4.

---

### OE-2: Autoren-Extraktion

`author_like` berechnet nur schwache heuristische Scores.
Autoren-Extraktion aus Fließtext funktioniert für einfache Fälle,
aber Institutionen und mehrteilige Namen werden oft falsch erkannt.

**Status:** Grundfunktion in Phase 1. Verbesserung in Phase 4.

---

### OE-3: Dokumenttyp-Klassifikation ✓

Regelbasiert über `early_meta`-Signale implementiert.
Testkorpus: 100% Genauigkeit auf 5 Dokumenten, 85% auf 21 Dokumenten.

---

### OE-4: Konfliktauflösung bei mehreren Katalogen

`atlas global search` fragt mehrere Kataloge sequenziell ab.
Duplikate (gleicher SHA-256) sollten erkannt und zusammengeführt werden.

**Status:** Offen. Relevant ab Phase 3.

---

### OE-5: Persistenz der DU-Zwischenergebnisse

Alle DU-Layer werden vollständig in SQLite persistiert.
Schätzung: ~50–100 KB pro Dokument für alle Layer.

**Status:** Option A (alle Layer persistent) in Phase 1+2.
Bewertung in Phase 4 nach Performance-Messungen.

---

### OE-6: i18n-Architektur

Section-Labels (Abstract, References, Appendix, …) sind
hartcodiert in `text_patterns.py` und `section_labels.py`.
Für mehrsprachige Korpora (DE/EN/FR) sollte ein `core/i18n/`
Modul mit YAML-basierten Übersetzungen gebaut werden.

**Status:** Zurückgestellt auf Phase 4.

---

### OE-7: Wikidata als Verbindungsknoten ✓

`enrich/wikidata.py` implementiert. Verbindet Atlas-interne URIs
mit Wikidata QIDs via `owl:sameAs`. Produktiver Einsatz sobald
Netzwerkzugang verfügbar.

---

### OE-8: Mehrsprachige Embeddings

`all-MiniLM-L6-v2` ist englisch-dominant. Deutsche Dokumente
erzielen Ähnlichkeits-Scores von 0.27–0.30 gegenüber englischen.

**Optionen:**
- A) `paraphrase-multilingual-MiniLM-L12-v2` — gleiche Dimension (384),
  direkt austauschbar, gute EN/DE/FR-Performance
- B) Sprach-spezifische Modelle pro Dokument — komplex
- C) Übersetzungs-Pipeline vor Embedding — aufwendig, verlustbehaftet

**Status:** Option A empfohlen für Phase 4. Erfordert `atlas dev du embed-all`.

---

### OE-9: Keyword-Qualität für Sacherschließung

YAKE auf Dokument-Ebene produziert für RVK/GND-Klassifikation
zu unspezifische Terme. Die Kette Keywords → GND → RVK ist nur
so gut wie der erste Schritt.

**Ansätze:**
- A) MultipartiteRank (pke) — graph-basiert, positionsbewusst,
  für wissenschaftliche Dokumente entwickelt
- B) Thesaurus-Boost — GND-Kandidaten in YAKE doppelt gewichten
- C) Sliding Window innerhalb von Kapiteln — Kapitelgrenzen
  respektieren, innerhalb langer Kapitel Fenstergranularität

**Status:** YAKE in Phase 2. Verbesserung in Phase 3.

---

## Bekannte Einschränkungen

**Nicht unterstützt:**
- Passwortgeschützte PDFs (werden mit Fehler abgelehnt)
- PDFs mit ausschließlich Vektorgrafiken ohne Text
- Rechts-nach-Links-Sprachen (Arabisch, Hebräisch)
- Sehr große PDFs (>500 Seiten) — DU-Pipeline läuft, aber langsam

**Bekannte Schwächen der DU-Pipeline:**
- Mehrspaltige Layouts: `body_like`-Scores ohne `column_hint` weniger präzise
- Letter-spaced Headings: erster Buchstabe geht bei Normalisierung verloren
- Tabelleninhalte: als Blöcke segmentiert, nicht als strukturierte Tabellen
- Mathematische Formeln und Formelblöcke: als Headings fehlklassifiziert
  (`Given:`, `Solution:`, `Answer:` — betrifft Timber Construction Manual)
- Captions: werden gelegentlich als `body` klassifiziert
- Titel: bei vielen Dokumenten kein Titelblock erkannt (`actual=''`)
- Laudel Dissertation: 0/8 Sections durch Zonierungsproblem

**Bekannte Schwächen der Erschließung:**
- Mehrsprachige Ähnlichkeitssuche: englisch-dominant (OE-8)
- RVK-Klassifikation: Treffsicherheit abhängig von Keyword-Qualität
- Topic-Extraktion: Monografien ohne Preface-Block landen im Kapitelinhalt
- GND-Suche: ohne Typ-Filter werden Personen und Körperschaften gefunden

---

## Qualitätsziele

| Metrik | Phase 1 | Phase 2 | Ziel Phase 4 |
|---|---|---|---|
| Dokumenttyp-Genauigkeit | 100% | 85% | 95% |
| Titel-Extraktion | 100% | 25% | 90% |
| Autoren-Extraktion | 57% | 32% | 85% |
| Section-Tree Precision | — | 13% | 0.70 |
| Section-Tree Recall | — | 77% | 0.85 |
| Section-Tree F1 | 54% | 23% | 0.75 |
| Semantische Ähnlichkeit EN→EN | — | 0.595 | 0.70 |
| Semantische Ähnlichkeit DE→EN | — | 0.30 | 0.55 (multilingual) |
| Topic-Qualität (korrekt) | — | 60% | 85% |
| RVK-Treffsicherheit | — | ~20% | 70% |
| Verarbeitungszeit pro Dokument | <10s | <15s | <10s |
