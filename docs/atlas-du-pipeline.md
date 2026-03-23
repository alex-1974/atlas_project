# Atlas — Document Understanding Pipeline

> Referenzdokument für [`atlas-rebuild-roadmap.md`](./atlas-rebuild-roadmap.md)  
> Beschreibt die DU-Pipeline: Layer, Inferenz, Repository, process/inspect.  
> Die Algorithmen sind bereits implementiert und funktionieren.  
> Dieser Port ändert nur die Persistenzschicht: psycopg → SQLite.

---

## Prinzip

Document Understanding ist der Schritt, mit dem Atlas von reinem Text Mining zu strukturellem Dokumentverständnis übergeht. Ein PDF wird Schicht für Schicht analysiert. Jede Schicht stellt eine bestimmte Frage an jeden Block — und die Antworten aller Schichten zusammen ergeben ein vollständiges Bild.

Kein Layer entscheidet allein. Erst die Kombination macht Aussagen möglich.

---

## Die zwei Kommandos

| Kommando | Rolle |
|---|---|
| `atlas dev du process <id>` | Berechnet den vollständigen DU-Zustand und schreibt ihn in die DB |
| `atlas dev du inspect <id>` | Liest den aktuellen DU-Zustand und visualisiert ihn im Terminal |

`du process` ist schreibend und idempotent: berechnet den Zustand neu.  
`du inspect` ist lesend: rechnet nichts, zeigt alles.

In der öffentlichen CLI läuft `du process` automatisch als Teil von `atlas add`.  
`atlas inspect <id>` zeigt eine Nutzersicht (Titel, Typ, Struktur) — nicht alle Layer.

---

## Die Pipeline-Reihenfolge

```
build_document
→ compute_geometry
→ compute_layout_graph
→ compute_layout_clusters
→ compute_typography
→ compute_surface
→ compute_context
→ compute_semantic_micro
→ compute_spacing_rhythm
→ compute_topology
→ compute_page_furniture
→ compute_signals
→ compute_roles
→ compute_consensus
→ compute_headings
→ compute_document_phase
→ compute_zones
→ compute_section_tree
→ compute_document_type
```

Diese Reihenfolge ist in `understanding/pipeline.py` festgelegt und darf nicht verändert werden, ohne die Abhängigkeiten zu prüfen.

---

## Die Layer im Detail

### Stufe 1 — Dokumentbasis

**`build_document`**  
Erzeugt aus extrahierten PDF-Daten die DU-Grundtabellen: Dokumentkontext, Seiten, Blöcke. Die Blockebene ist die Basis für alles Weitere.

---

### Stufe 2 — Low-level Layer (Messung, keine Interpretation)

**`compute_geometry`**  
Räumliche Merkmale: Bounding Boxes, Seiten- und Dokumentkoordinaten, Breite/Höhe, Zentrierung, Spaltenhinweise.

**`compute_layout_graph`**  
Nachbarschafts- und Layoutbeziehungen zwischen Blöcken.

**`compute_layout_clusters`**  
Gruppierung ähnlicher Layoutmuster.

**`compute_typography`**  
Font Family, Font Size, Bold/Italic, Small Caps, All Caps, Fontwechsel.

**`compute_surface`**  
Textoberflächenmerkmale: Zeichenzahl, Wortzahl, Punkt-/Zifferndichte, DOI/Year/URL-Indikatoren.

**`compute_context`**  
Frühe Kontextsignale: `front_matter_score`, `body_score`, `back_matter_score`, Dokument- und Seitenposition.

**`compute_semantic_micro`**  
Explizite kleine Marker: `is_abstract_marker`, `is_keywords_marker`, `is_references_marker`, `is_figure_marker`, `is_table_marker`, `is_appendix_marker`.

**`compute_spacing_rhythm`**  
Zeilenabstände, Absatzlücken, Einrückungen, Region Breaks.

**`compute_topology`**  
Seitenübergreifende und strukturelle Beziehungen.

**`compute_page_furniture`**  
Header/Footer/Seitenzahl-Signale: `is_top_band`, `is_bottom_band`, `running_header_like`, `repeated_across_pages`.

---

### Stufe 3 — Signal- und Rollenebene (Einschätzung)

**`compute_signals`**  
Kombiniert Low-level-Layer zu benannten Signalen pro Block:
`title_like`, `author_like`, `heading_like`, `reference_like`, `caption_like`, `noise_like`.

**`compute_roles`**  
Leitet diskrete Blockrollen aus Signalen ab:
`heading`, `body`, `title`, `reference`, `caption`, `noise`.

**`compute_consensus`**  
Harmonisiert widersprüchliche Einzelsignale. Stabilisiert Rollenzuweisungen.

---

### Stufe 4 — Heading-Erkennung

**`compute_headings`**  
Berechnet Heading-Kandidaten und schreibt sie in `du_heading_candidates`.  
Wichtig: Headings und Zonen sind entkoppelt. Headings destabilisieren Zonen nicht mehr.

```
Blocksignale → Heading-Kandidaten
```

---

### Stufe 5 — Dokumentphasen & Zonen

**`compute_document_phase`**  
Zwischenstufe für grobe Dokumentphasen.

**`compute_zones`**  
Kanonische globale Zonierung in `front`, `body`, `back`.  
Heading-unabhängig, arbeitet aus Blocksignalen.  
Schreibt in `du_zone_hypotheses` und `du_semantic_zones`.

---

### Stufe 6 — Section Tree

**`compute_section_tree`**  
Baut aus Heading-Kandidaten und finalen Semantic Zones eine hierarchische Dokumentstruktur in `du_section_tree`.

```
L1 Terminology
  L2 Building type
  L2 Open-hall plan details
L1 Conclusions
L1 References
```

---

### Stufe 7 — Dokumenttyp

**`compute_document_type`**  
Klassifiziert das Dokument: `journal_article`, `archival_text`, weitere Typen.

---

## Was `du process` schreibt

| Tabelle | Inhalt |
|---|---|
| `du_document_context` | Dokumentkontext |
| `du_pages` | Seiten |
| `du_blocks` | Blöcke (Basisebene) |
| `du_block_geometry` | Geometrie pro Block |
| `du_block_typography` | Typografie pro Block |
| `du_block_surface_features` | Oberflächenmerkmale |
| `du_block_context` | Kontextscores |
| `du_block_semantic_micro` | Explizite Marker |
| `du_block_spacing_rhythm` | Abstände |
| `du_block_topology` | Topologie |
| `du_block_topology_signals` | Topologie-Signale |
| `du_block_page_furniture_signals` | Furniture-Signale |
| `du_block_layout_features` | Layout-Features |
| `du_block_signals` | Kombinierte Signale |
| `du_block_roles` | Diskrete Rollen |
| `du_zone_hypotheses` | Zonen-Hypothesen (scored) |
| `du_semantic_zones` | Finale Zonen |
| `du_heading_candidates` | Heading-Kandidaten |
| `du_section_tree` | Hierarchische Struktur |
| `du_document_model` | Dokumentmodell |
| `documents.du_document_type` | Klassifikation |

---

## Repository — Port-Anforderungen

Das `Repository` in `understanding/persistence/repository.py` ist die einzige Stelle, die direkt mit der Datenbank spricht. Beim Port auf SQLite gelten diese Regeln:

1. **Signaturen bleiben.** Alle `store_*`- und `fetch_*`-Methoden behalten ihre Parameter und Rückgabetypen.
2. **Nur das Backend ändert sich.** `psycopg`-Aufrufe werden durch `sqlite3`-Aufrufe ersetzt.
3. **Transaktionen.** SQLite ist standardmäßig autocommit — explizite Transaktionen verwenden.
4. **UUIDs.** SQLite hat keinen nativen UUID-Typ — als `TEXT` speichern.
5. **Timestamps.** Als ISO-8601-String speichern.

---

## Verbindung zum Wissensgraph (Phase 4)

`du process` markiert erkannte Referenzblöcke (`role = 'reference'`). In Phase 4 werden diese ausgelesen und als `cites`-Tripel in Oxigraph geschrieben. Das ist die direkte Verbindung zwischen DU-Pipeline und Wissensgraph.

Die Referenzblöcke liegen in `du_block_roles` mit `role = 'reference'` und dem zugehörigen Text in `du_blocks`.

---

## `du inspect` — Ausgabestruktur

```
== Document Type ==
{'primary_type': 'journal_article', ...}

[049] heading ? - p5 Open-hall plan details
  geometry:   x0=72 y0=341 width=0.82 page_y=0.44
  typography: font=TimesNewRoman size=12.0 bold=True
  signals:    heading_like=0.91 body_like=0.02
  role:       heading

== Zone Hypotheses ==
front   [000-028] conf=0.78
body    [029-132] conf=0.86
back    [133-168] conf=0.90

== Semantic Zones ==
front   [000-028]
body    [029-132]
back    [133-168]

== Section Tree ==
  - L1 [007-007] Terminology
    - L2 [026-026] Building type
    - L2 [049-049] Open-hall plan details

== Document Type (Top-k) ==
 1 journal_article   score=0.58
 2 archival_text     score=0.00
```
