# atlas.parse

`atlas.parse` ist das parsernahe Dokumentanalyse-Subpackage von Atlas.

Es extrahiert strukturierte, dokumentinterne Informationen aus einzelnen PDFs
und stellt sie Atlas über eine kleine, stabile API zur Verfügung.

## Leitprinzip

> `atlas.parse` ist ein Werkzeug von Atlas, nicht sein Kern.

Atlas nutzt `atlas.parse`, um PDFs in strukturierte Dokumentbefunde zu
überführen. Persistenz, Kataloglogik, Ranking, Wissensgraph, semantische
Suche und Nutzerfunktionen gehören nicht zu `atlas.parse`.

---

## Zuständigkeit von `atlas.parse`

`atlas.parse` ist zuständig für:

- parsernahe PDF-Akquisition
- Text- und Blockextraktion
- Segmentierung
- Dokumentstruktur
- dokumentinterne Rollen und Zonen
- Metadatenextraktion
- Identifikatoren
- Referenzdetektion und -zerlegung
- Dokumenttyp-Klassifikation

`atlas.parse` ist **nicht** zuständig für:

- Datenbankzugriffe
- Katalogpersistenz
- Embeddings
- semantische Suche auf Katalogebene
- Ranking von Wichtigkeit
- Wissensgraph über mehrere Dokumente
- externe Anreicherung (Wikidata, Crossref, ...)
- Annotationen, Sammlungen, Nutzerlogik

---

## Öffentliche API

```python
from atlas.parse import analyze_document

result = analyze_document("paper.pdf")
