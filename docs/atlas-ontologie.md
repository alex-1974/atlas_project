# Atlas — Wissensgraph-Ontologie

> Referenzdokument für [`atlas-rebuild-roadmap.md`](./atlas-rebuild-roadmap.md)  
> Entitäten, Beziehungen und Turtle-Schema des Atlas-Wissensgraphen.

---

## Prinzip

Der Wissensgraph speichert Beziehungen als RDF-Tripel in Oxigraph.  
Jedes Tripel hat die Form: `Subjekt → Prädikat → Objekt`.

```
Paper       → authored_by    → Autor
Paper       → cites          → Paper
Konzept     → introduced_in  → Paper
Autor       → affiliated_with → Institution
```

Die Ontologie liegt als `ontology.ttl` im `.atlas/`-Ordner — menschenlesbar, versionierbar, erweiterbar.

---

## Entitäten (Knoten)

```turtle
# Dokumente
atlas:Document
atlas:Paper          rdfs:subClassOf atlas:Document
atlas:Book           rdfs:subClassOf atlas:Document
atlas:Chapter        rdfs:subClassOf atlas:Document
atlas:Thesis         rdfs:subClassOf atlas:Document

# Personen & Institutionen
atlas:Person
atlas:Author         rdfs:subClassOf atlas:Person
atlas:Institution

# Wissen
atlas:Concept        # z.B. "Transformer", "Backpropagation"
atlas:Topic          # z.B. "Deep Learning", "NLP"
atlas:Method         # z.B. "Gradient Descent", "Attention"
atlas:Dataset        # z.B. "ImageNet", "MNIST"

# Publikationsorgane
atlas:Journal
atlas:Conference
atlas:Publisher

# Klassifikation
atlas:RVKClass
atlas:GNDConcept
```

---

## Beziehungen (Kanten)

```turtle
# Autorschaft
atlas:authored_by          Domain: Document    Range: Author
atlas:affiliated_with      Domain: Author      Range: Institution

# Referenzen
atlas:cites                Domain: Document    Range: Document
atlas:extends              Domain: Document    Range: Document

# Konzepte
atlas:introduces           Domain: Document    Range: Concept
atlas:about                Domain: Document    Range: Topic
atlas:uses_method          Domain: Document    Range: Method
atlas:uses_dataset         Domain: Document    Range: Dataset

# Publikation
atlas:published_in         Domain: Document    Range: Journal|Conference
atlas:published_by         Domain: Document    Range: Publisher

# Identifikatoren
atlas:has_doi              Domain: Document    Range: Literal
atlas:has_arxiv_id         Domain: Document    Range: Literal
atlas:has_isbn             Domain: Document    Range: Literal
atlas:has_pmid             Domain: Document    Range: Literal

# Klassifikation
atlas:has_rvk_class        Domain: Document    Range: RVKClass
atlas:has_gnd_keyword      Domain: Document    Range: GNDConcept

# Externe Verknüpfungen
owl:sameAs                 Domain: any         Range: Wikidata-URI
```

---

## Herkunft der Tripel

| Tripel | Quelle | Phase |
|---|---|---|
| `authored_by` | DU-Extraktion + Metadaten | Phase 2 |
| `published_in` | Metadaten + CrossRef | Phase 1/5 |
| `has_doi`, `has_arxiv_id`, ... | Identifier-Extraktion | Phase 1 |
| `cites` | DU-Referenzblöcke | Phase 4 |
| `introduces`, `about` | Manuelle Annotation / GND | Phase 5 |
| `owl:sameAs` | Wikidata-Anreicherung | Phase 5 |
| `has_rvk_class` | RVK-API | Phase 5 |
| `has_gnd_keyword` | GND-API | Phase 5 |

---

## Beispiel-Tripel

```turtle
# Ein Paper und seine Autoren
atlas:attention_2017   atlas:authored_by    atlas:vaswani .
atlas:attention_2017   atlas:authored_by    atlas:shazeer .
atlas:attention_2017   atlas:published_in   atlas:neurips_2017 .
atlas:attention_2017   atlas:has_doi        "10.48550/arXiv.1706.03762" .
atlas:attention_2017   owl:sameAs           <https://www.wikidata.org/entity/Q59818> .

# Zitation
atlas:bert_2018        atlas:cites          atlas:attention_2017 .
atlas:bert_2018        atlas:extends        atlas:attention_2017 .
```

---

## SPARQL-Abfragen hinter den CLI-Kommandos

### `atlas refs <pdf>`

```sparql
SELECT ?cited ?title WHERE {
    <atlas:DOC_ID> atlas:cites ?cited .
    OPTIONAL { ?cited atlas:title ?title . }
}
```

### `atlas graph --author "Vaswani"`

```sparql
SELECT ?coauthor WHERE {
    ?paper atlas:authored_by atlas:vaswani .
    ?paper atlas:authored_by ?coauthor .
    FILTER(?coauthor != atlas:vaswani)
}
```

### `atlas concept "Backpropagation"`

```sparql
SELECT ?paper WHERE {
    ?paper atlas:about atlas:backpropagation .
}
UNION
SELECT ?paper WHERE {
    ?paper atlas:introduces atlas:backpropagation .
}
```

---

## Technologie: Oxigraph

- Lokaler RDF/SPARQL-Store: kein Server, kein Daemon
- Python-Paket: `pyoxigraph`
- Store-Pfad: `.atlas/knowledge/`
- Ontologie wird beim `atlas init` aus dem Package kopiert und in den Store geladen

```python
from pyoxigraph import Store, NamedNode, Triple

store = Store(".atlas/knowledge")

store.add(Triple(
    NamedNode("atlas:attention_2017"),
    NamedNode("atlas:cites"),
    NamedNode("atlas:seq2seq_2014")
))
```

---

## Verbindung zur DU-Pipeline

In Phase 4 werden erkannte Referenzblöcke aus `du_block_roles` ausgelesen:

```sql
SELECT b.block_id, b.text
FROM du_blocks b
JOIN du_block_roles r ON b.block_id = r.block_id
WHERE b.document_id = ? AND r.role = 'reference'
```

Der Text jedes Referenzblocks wird geparst — Autorname, Jahr, Titel, DOI — und als `cites`-Tripel in Oxigraph geschrieben. Das ist die direkte Brücke zwischen Document Understanding und Wissensgraph.
