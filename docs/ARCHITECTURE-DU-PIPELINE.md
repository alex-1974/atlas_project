# Atlas — Document Understanding Pipeline

## Ziel und Prinzip

Die DU-Pipeline verwandelt ein rohes PDF in ein strukturiertes Modell:
Titel, Autor, Dokumenttyp, Zonen (Frontmatter/Body/Backmatter) und
einen Section Tree mit L1–L3 Headings.

**Leitprinzip: Opportunistisch statt erzwingend.**
Atlas versucht nicht, jedes Dokument vollständig zu verstehen.
Wenn kein hochkonfidentes Heading-Pattern erkennbar ist, bleibt der
Section Tree leer — das ist korrekt und besser als geraten. Reine
Fließtexte werden als solche erkannt.

**Alle Signale sind dokumentrelativ.**
Fontgröße, Abstände und Farben werden immer relativ zu den Normen des
jeweiligen Dokuments gemessen — nie als absolute Werte. Ein 12pt-Heading
in einem Dokument mit 10pt-Fließtext ist dasselbe Signal wie ein 16pt-Heading
in einem Dokument mit 14pt-Fließtext: font_ratio = 1.2.

---

## Überblick: Verarbeitungspasses

```
Pass 0   DocumentProfile        profiling.py
         → book_score, structure_score, Quadrant

Pass 1   Segmentation           segmentation/blocks.py
         → du_blocks, source_kind (born_digital | ocr_scan | image_pdf)

Pass 1   Messung (Layer 1)      measure/*.py
         → du_block_geometry, du_block_typography, du_block_surface,
           du_block_spacing, du_block_furniture, du_block_topology,
           du_block_context, du_block_semantic_micro

Pass 1.5 TypographyProfile      measure/typography_profile.py (NEU)
         → body_font, gap_norm, font_classes, flow_threshold

Pass 2   Signalaggregation      aggregate/signals.py
         → du_block_signals (dokumentrelativ, mit TypographyProfile)

Pass 2.5 Graph-Korrekturen      graph/corrections.py
         → lokale Konsistenz, Nachbarschaftsbeziehungen

Pass 3   Interpretation (Layer 3)
   3.1   Rollen                 interpret/roles.py
         → du_block_roles: heading | body | title | author |
                            reference | caption | noise | page_furniture
   3.2   Konsensus              interpret/consensus.py
   3.3   Zonierung              interpret/zones.py
         → du_block_zones: FRONT_MATTER | BODY | BACK_MATTER
   3.4   Anchor Detection       interpret/anchor_detection.py (NEU)
         → hochkonfidente Heading-Blöcke identifizieren
         → HeadingPattern pro Level lernen
   3.5   Heading-Kandidaten     interpret/headings.py
         → du_heading_candidates (Pattern-basiert)
   3.6   Section Tree           interpret/section_tree.py
         → du_section_tree: L1–L3 (tiefer nur bei nummerierter Gliederung)
   3.7   Dokumenttyp            interpret/document_type.py
```

---

## Pass 0 — DocumentProfile

`pipeline/profiling.py` klassifiziert das Dokument vor der eigentlichen
Verarbeitung in einen von vier Quadranten:

```
book_score    = flinear(page_count, lo=30, hi=150)
structure_score = 0.7 × markword_signal + 0.3 × font_signal

Quadranten:
  book_structured    → Buch mit klarer Gliederung (Timber Manual)
  book_unstructured  → Buch ohne klare Gliederung
  doc_structured     → Kurzdokument mit Gliederung (Historic England)
  doc_unstructured   → Kurzdokument ohne Gliederung (Suffolk Essay)
```

Das Profil steuert die Erwartungen: `book_structured` hat wahrscheinlich
einen TOC und tiefe Heading-Hierarchie; `doc_unstructured` hat
möglicherweise gar keine Headings.

---

## Pass 1.5 — TypographyProfile

`measure/typography_profile.py` baut ein dokumentrelatives Typografie-Modell
aus allen Blöcken. Wird nach Layer 1 (Messung) und vor Layer 2 (Aggregation)
aufgerufen.

```python
@dataclass
class TypographyProfile:
    body_font:     float   # dominante Schriftgröße (nach Zeichenanzahl)
    gap_norm:      float   # medianer whitespace_before unter Body-Blöcken (pt)
    gap_p75:       float   # 75. Perzentile
    gap_p90:       float   # 90. Perzentile
    font_classes:  list[FontClass]  # Cluster sortiert nach font_ratio desc
    flow_threshold: float  # in_flow_score ab dem ein Block "eingebettet" gilt
```

**FontClass — ein Typografie-Cluster:**
```python
@dataclass
class FontClass:
    label:          str    # "body" | "small" | "sub_h" | "mid_h" | "large_h"
    font_ratio_min: float  # font_size / body_font
    font_ratio_max: float
    bold:           bool | None
    is_all_caps:    bool | None
    block_count:    int
    heading_level:  int | None  # 1-basiert, None wenn kein Heading
```

**Clustering-Algorithmus:**
1. font_ratio = font_size / body_font für jeden Block
2. Runden auf 0.05-Buckets, gruppieren nach (ratio_bucket, bold)
3. Blöcke mit < 3 Zeichen oder > 8× body_font ausschließen (Grafiken)
4. Labels: `body` (0.85–1.15, nicht bold), `sub_h` (bold bei body-size
   oder 1.05–1.25), `mid_h` (1.25–1.60), `large_h` (>1.60), `small` (<0.85)
5. Heading-Level aus Rang der nicht-body, nicht-small Klassen

**Dokumentrelative Messungen:**
- `font_ratio(fs)` = fs / body_font
- `relative_gap(gap)` = whitespace_before / gap_norm
- `is_embedded(flow)` = in_flow_score > flow_threshold

---

## Pass 3.4 — Anchor Detection (neu)

`interpret/anchor_detection.py` identifiziert hochkonfidente Heading-Blöcke
als Anker für das Pattern-Lernen.

**Tier-1-Anker (hochkonfident):**
Alle drei Bedingungen erfüllt:
- Typografie in einer heading FontClass (laut TypographyProfile)
- `relative_gap > 1.5` (mehr Abstand als normal)
- `in_flow_score < 0.75` (nicht im Textfluss eingebettet)

**Tier-2-Anker (sehr hochkonfident):**
Tier-1 plus mindestens eines von:
- `starts_with_number` (z.B. `1.2 Materials`, `3.2.1 Dead Loads`)
- TOC-Match (Titel erscheint im TOC)
- ALL_CAPS bei `font_ratio > 1.5`

**HeadingPattern je Level:**
Aus den Ankern wird für jeden Level ein Pattern gelernt:
```python
@dataclass
class HeadingPattern:
    level:          int
    font_ratio_min: float
    font_ratio_max: float
    bold:           bool | None
    all_caps:       bool | None
    gap_rel_min:    float      # whitespace_before / gap_norm Minimum
    flow_max:       float      # maximaler in_flow_score
    number_re:      str | None # Nummerierungsmuster (regex)
    confidence:     float      # Anteil Tier-2 unter den Ankern
```

**Opportunistisch:**
- Keine Anker gefunden → kein Pattern → Section Tree bleibt leer
- confidence < 0.3 → nur L1 wenn vorhanden
- confidence ≥ 0.7 → volle Pattern-Anwendung bis L3

---

## Pass 3.5 — Heading-Kandidaten

`interpret/headings.py` nutzt HeadingPatterns wenn vorhanden.
Fallback auf Score-basierten Ansatz (bisherige Logik) wenn kein Pattern.

**Pattern-basierte Selektion:**
```
Ein Block ist Heading-Kandidat wenn:
  Pattern vorhanden:
    → Typografie matcht HeadingPattern UND
    → in_flow_score < pattern.flow_max UND
    → relative_gap > pattern.gap_rel_min × 0.5

  Kein Pattern (Fallback):
    → bisherige _should_keep Logik mit heading_score
```

**Harte Ausschlüsse (immer, unabhängig vom Pattern):**
- `in_flow_score > flow_threshold` (0.85) → body, egal wie die Typografie
- `running_header_like OR repeated_across_pages` → page_furniture
- `ends_with_colon AND in_flow_score > 0.7` → Rechenschritt
- Markword-Patterns: `EXAMPLE N.N-N`, `Table N.N-N`, `Figure N.N-N` → caption

---

## Pass 3.6 — Section Tree

`interpret/section_tree.py` baut die Hierarchie aus Heading-Kandidaten.

**Level-Zuweisung (Priorität):**
1. Nummerierungstiefe: `1.2.3 Titel` → L3 (stärktes Signal)
2. TOC-Match: Level aus TOC
3. HeadingPattern: Level aus `pattern.level`
4. TypographyProfile: `font_class.heading_level`
5. Style-Model (Fallback): bisherige Clustering-Logik

**Tiefenbegrenzung:**
- L4+ nur bei expliziter Nummerierung oder TOC-Nachweis
- Ohne Nummerierung: maximal L3

---

## Drei-Schichten-Modell

Die ursprüngliche Drei-Schichten-Architektur bleibt erhalten.
TypographyProfile und Anchor Detection ergänzen sie als neue Zwischenschichten.

```
Schicht 1: Messen         (geometry, typography, surface, spacing, ...)
           ↓ TypographyProfile (body_font, gap_norm, font_classes)
Schicht 2: Aggregieren    (signals.py — dokumentrelativ)
           ↓ Anchor Detection (HeadingPatterns)
Schicht 3: Interpretieren (roles, zones, headings, section_tree)
```

**Strenge Trennung:**
- Schicht 1 misst, urteilt nicht
- Schicht 2 aggregiert, urteilt nicht
- Schicht 3 interpretiert auf Basis aller Messungen und des Profils
- `understanding/` kennt `knowledge/` und `embeddings/` nicht

---

## Datenbankschema (DU-Tabellen)

Bestehende Tabellen bleiben unverändert. Neue Tabellen:

```sql
-- TypographyProfile pro Dokument (neu in Phase 3)
CREATE TABLE du_typography_profile (
    document_id     TEXT PRIMARY KEY REFERENCES documents(document_id),
    body_font       REAL,
    gap_norm        REAL,
    gap_p75         REAL,
    gap_p90         REAL,
    flow_threshold  REAL,
    font_classes    TEXT,  -- JSON: [{label, ratio_min, ratio_max, bold, ...}]
    created_at      TEXT DEFAULT (datetime('now'))
);

-- HeadingPatterns pro Dokument (neu in Phase 3)
CREATE TABLE du_heading_patterns (
    pattern_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     TEXT NOT NULL REFERENCES documents(document_id),
    level           INTEGER NOT NULL,
    font_ratio_min  REAL,
    font_ratio_max  REAL,
    bold            INTEGER,
    all_caps        INTEGER,
    gap_rel_min     REAL,
    flow_max        REAL,
    number_re       TEXT,
    confidence      REAL,
    anchor_count    INTEGER
);
```

---

## OCR-Modus

Bei `source_kind = 'ocr_scan'` (erkannt durch `avg_font > 20` bei
gleichzeitig `avg_x0_dev > 500`):
- Layer 1 läuft vollständig
- TypographyProfile läuft, aber `flow_threshold` wird erhöht (0.70 statt 0.85)
- Heading-Erkennung: nur ALL_CAPS-Blöcke mit hohem Heading-Score
- Section Tree: nur L1, nur hochkonfident

Bei `source_kind = 'image_pdf'` (kein Text-Layer):
- Layer 1 läuft, Layer 2 und 3 werden übersprungen

---

## Zwei-Pass-Ansatz

Layer 3 läuft zweimal um das Henne-Ei-Problem zu lösen:

```
Pass 1: Rollen ohne Dokumenttyp-Anpassung
        → Dokumenttyp erkennen (compute_document_type)
Pass 2: Rollen mit Dokumenttyp-Anpassung
        → Section Tree mit vollständiger Information
```

TypographyProfile und HeadingPatterns werden einmal vor Pass 1
berechnet und in beiden Passes verwendet.

---

## Qualitätsziele (Phase 3)

| Metrik | Phase 2 | Ziel Phase 3 |
|---|---|---|
| Titel-Extraktion | 25% | 80% |
| Section-Tree Precision | 13% | 60% |
| Section-Tree Recall | 77% | 75% |
| Section-Tree F1 | 23% | 67% |
