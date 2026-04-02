# Atlas — Wissensgraph

## Zweck

Der Wissensgraph speichert Beziehungen zwischen Dokumenten, Personen
und Konzepten als RDF-Tripel. Er macht Fragen beantwortbar, die
eine relationale Datenbank nicht gut beantwortet: Wer hat mit wem
publiziert? Welche Dokumente zitiert dieses Paper? Welche Arbeiten
behandeln dasselbe Konzept?

---

## Technologie

**Oxigraph** — lokaler RDF/SPARQL-Store, kein Server, kein Daemon.
Python-Paket: `pyoxigraph 0.5`. Store-Pfad: `.atlas/knowledge/`.

**Named Graphs:** Jedes Dokument bekommt einen eigenen Named Graph
(`https://atlas.local/doc/{document_id}/graph`). Alle Tripel eines
Dokuments werden darin gespeichert. Das ermöglicht atomares Löschen
beim `atlas remove` und sauberes Re-Enrichment.

**Wichtig für SPARQL:** Da Tripel in Named Graphs liegen (nicht im
Default Graph), müssen alle Queries `GRAPH ?g { ... }` verwenden.

```python
# knowledge/sparql.py — alle Queries haben diese Struktur
SELECT ?a WHERE { GRAPH ?g { ?d atlas:authored_by ?a . } }
```

---

## Entitäten (Knoten)

```turtle
# Dokumente — in triples.py geschrieben als Paper, Book, Report (nicht Document)
atlas:Paper          rdfs:subClassOf atlas:Document
atlas:Book           rdfs:subClassOf atlas:Document
atlas:Report         rdfs:subClassOf atlas:Document
atlas:Thesis         rdfs:subClassOf atlas:Document
atlas:Chapter        rdfs:subClassOf atlas:Document

# Personen & Institutionen
atlas:Author         rdfs:subClassOf atlas:Person
atlas:Institution

# Wissen
atlas:Concept        # z.B. "Hallenhaus", "Backpropagation"
atlas:Topic          # z.B. "Historische Bauforschung", "NLP"
atlas:Method         # z.B. "Gradient Descent", "Dendrochronologie"

# Publikationsorgane
atlas:Journal
atlas:Conference
atlas:Publisher

# Klassifikation
atlas:RVKClass
atlas:GNDConcept

# Erschließung (Phase 2)
atlas:Keyword        # YAKE-extrahierter Term
atlas:Theme          # RVK-Label oder Wikidata main_subject
```

---

## Beziehungen (Kanten)

```turtle
# Autorschaft
atlas:authored_by          Domain: Document    Range: Author
atlas:affiliated_with      Domain: Author      Range: Institution

# Referenzen (noch nicht vollständig — Referenz-Parser Phase 3)
atlas:cites                Domain: Document    Range: Document
atlas:extends              Domain: Document    Range: Document

# Konzepte
atlas:introduces           Domain: Document    Range: Concept
atlas:about                Domain: Document    Range: Topic
atlas:uses_method          Domain: Document    Range: Method

# Publikation
atlas:published_in         Domain: Document    Range: Journal|Conference
atlas:published_by         Domain: Document    Range: Publisher

# Identifikatoren
atlas:has_doi              Domain: Document    Range: Literal
atlas:has_arxiv_id         Domain: Document    Range: Literal
atlas:has_isbn             Domain: Document    Range: Literal
atlas:has_pmid             Domain: Document    Range: Literal
atlas:has_orcid            Domain: Author      Range: Literal

# Klassifikation
atlas:has_rvk_class        Domain: Document    Range: RVKClass
atlas:has_gnd_keyword      Domain: Document    Range: GNDConcept

# Erschließung (Phase 2)
atlas:has_keyword          Domain: Document    Range: Keyword
atlas:topic                Domain: Document    Range: Literal

# Externe Verknüpfungen
owl:sameAs                 Domain: any         Range: Wikidata-URI | GND-URI
```

---

## Herkunft der Tripel

| Tripel | Quelle | Zeitpunkt |
|---|---|---|
| `rdf:type` (Paper/Book/Report) | DU `du_document_type` | `atlas add` |
| `authored_by` | DU-Extraktion + Metadaten | `atlas add` |
| `rdfs:label` (Autor) | DU + Metadaten | `atlas add` |
| `has_doi`, `has_arxiv_id` | Identifier-Extraktion | `atlas add` |
| `published_in` | Metadaten + CrossRef | `atlas add` / `atlas enrich --crossref` |
| `has_keyword` | YAKE-Extraktion | `atlas enrich --keywords` |
| `topic` | GND-normalisiert | `atlas enrich --topic` |
| `has_gnd_keyword` | lobid.org | `atlas enrich --gnd` |
| `about` (Theme) | RVK-Label / Wikidata | `atlas enrich --themes` |
| `has_rvk_class` | RVK-API | `atlas enrich --rvk` |
| `owl:sameAs` (Wikidata) | Wikidata-API | `atlas enrich --wikidata` |
| `has_orcid` | ORCID-API | `atlas enrich --wikidata` |
| `cites` | Referenz-Parser (Phase 3) | `atlas enrich` |

### Brücke DU → Wissensgraph

`atlas add` liest nach der DU-Pipeline die Ergebnisse aus SQLite
und schreibt lokale Tripel (Typ, Autor, Identifier) in Oxigraph.
Externe Anreicherung (GND, RVK, Wikidata) erfolgt separat via
`atlas enrich`.

```python
# knowledge/triples.py — beim atlas add aufgerufen
from atlas.knowledge.triples import write_document_to_store
n = write_document_to_store(conn, store, document_id)
# → schreibt rdf:type, authored_by, has_doi etc. in Named Graph
```

Der Referenz-Parser (Phase 3) wird aus `role = 'reference'`-Blöcken
`cites`-Tripel erzeugen. Aktuell (Phase 2) enthält der Graph noch
keine Zitations-Tripel aus dem Dokumenttext.

---

## Aktueller Stand (Testkorpus 5 Dokumente)

```
Dokumente:   5  (Paper: 3, Report: 1, Monograph: 1)
Autoren:     5
Zitationen:  314  (aus Referenzblöcken, noch nicht als cites-Tripel)
Wikidata:    0  (braucht Netz)
ORCIDs:      0  (braucht Netz)
```

Zählung via `atlas knowledge.sparql.graph_stats()`.

---

## SPARQL-Abfragen hinter CLI-Kommandos

Alle Queries verwenden `GRAPH ?g { ... }` da Tripel in Named Graphs liegen.

### `atlas refs <id>` — Referenznetzwerk

```sparql
PREFIX atlas: <https://atlas.local/ontology#>
SELECT DISTINCT ?cited ?title WHERE {
  GRAPH ?g {
    <https://atlas.local/doc/DOC_ID> atlas:cites ?cited .
    OPTIONAL { ?cited atlas:title ?title . }
  }
}
```

### `atlas graph --author "Stiewe"` — Co-Autoren

```sparql
PREFIX atlas: <https://atlas.local/ontology#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?coauthor ?coauthorLabel WHERE {
  GRAPH ?g {
    ?author rdfs:label ?authorLabel .
    FILTER(LCASE(STR(?authorLabel)) = "stiewe")
    ?paper atlas:authored_by ?author .
    ?paper atlas:authored_by ?coauthor .
    FILTER(?coauthor != ?author)
    OPTIONAL { ?coauthor rdfs:label ?coauthorLabel . }
  }
}
```

### `atlas concept "Hallenhaus"` — Konzept-Suche

```sparql
PREFIX atlas: <https://atlas.local/ontology#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?paper ?title ?rel WHERE {
  GRAPH ?g {
    { ?paper atlas:about ?concept . BIND("about" AS ?rel) }
    UNION
    { ?paper atlas:introduces ?concept . BIND("introduces" AS ?rel) }
    FILTER(
      CONTAINS(LCASE(STR(?concept)), "hallenhaus") ||
      EXISTS { ?concept rdfs:label ?l . FILTER(CONTAINS(LCASE(STR(?l)), "hallenhaus")) }
    )
    OPTIONAL { ?paper atlas:title ?title . }
  }
}
```

---

## Python-Integration

```python
from atlas.knowledge.store import KnowledgeStore
from atlas.knowledge.sparql import graph_stats, references_for_document

# Store öffnen
store = KnowledgeStore.open(catalog_root)

# Statistiken
stats = graph_stats(store)
# → {'documents': 5, 'authors': 5, 'citations': 314, ...}

# Referenzen eines Dokuments
refs = references_for_document(store, document_id, depth=1)
# → [{'uri': ..., 'title': ..., 'doi': ..., 'document_id': ...}]

# Tripel direkt hinzufügen
store.add_doc_triples(document_id, [
    (doc_node, pred_node, value_node),
    ...
])
```

**pyoxigraph 0.5 API-Hinweise:**

```python
# QuerySolutions: variables auf dem Ergebnisobjekt, nicht auf der Row
results = store._store.query(sparql)
variables = [str(v).lstrip("?") for v in results.variables]
for row in results:
    d = {var: row[i] for i, var in enumerate(variables) if row[i] is not None}

# NamedNode und Literal haben .value für den rohen String
node.value   # → "https://atlas.local/doc/..."
literal.value # → "Hallenhaus"
```

---

## Designprinzipien

**Named Graphs pro Dokument.** Jedes Dokument hat seinen eigenen
Graph. Das ermöglicht atomares Löschen (`atlas remove`) und
Re-Enrichment ohne Kollisionen.

**Graph wächst inkrementell.** `atlas add` schreibt lokale Tripel.
`atlas enrich` fügt externe Tripel hinzu. Bestehende Tripel werden
bei `atlas enrich` neu geschrieben (remove + add).

**Schwache Verbindungen sind erlaubt.** Ein `cites`-Tripel
auf ein Dokument, das noch nicht im Katalog ist, ist valide.
Der Knoten existiert, hat nur keine weiteren Attribute.

**Externe Identitäten über `owl:sameAs`.** Atlas-interne URIs
(`https://atlas.local/doc/{id}`) werden über `owl:sameAs` mit
Wikidata-URIs verbunden. Das ermöglicht zukünftige Federation
ohne Umbenennung interner Bezeichner.

**GND als Brücke zu kontrollierten Vokabularen.** GND-Entitäten
werden als `https://d-nb.info/gnd/{id}` referenziert. Das verbindet
den Atlas-Graph mit der Deutschen Nationalbibliografie.

→ CLI-Kommandos: [`CLI.md`](./CLI.md)
→ Datenbankschema (SQLite-Seite): [`DATABASE.md`](./DATABASE.md)
