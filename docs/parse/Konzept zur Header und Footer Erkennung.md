# **Konzept zur Header- und Footer-Erkennung in Atlas**

## 1. Zielsetzung

Die zuverlässige Erkennung von Headern und Footern ist eine zentrale Voraussetzung für das Dokumentverständnis von Atlas. Sie ermöglicht:

* die korrekte Extraktion des Fließtexts,
* die Identifikation der Dokumentstruktur,
* die Verbesserung der Keyword- und Metadatenanalyse,
* die präzise Navigation innerhalb eines PDF-Dokuments.

Header und Footer werden gemeinsam als **Furniture** bezeichnet und als wiederkehrende horizontale Bänder modelliert.

---

## 2. Grundprinzip

Die Erkennung basiert auf zwei komplementären Strategien:

1. **Globale Mustererkennung (statistisch)**
2. **Lokale Seitenheuristik (seitenweise)**

Diese Kombination gewährleistet sowohl Robustheit bei langen Dokumenten als auch Zuverlässigkeit bei kurzen oder unregelmäßig strukturierten PDFs.

---

## 3. Definition von Header und Footer

| Element       | Definition                                                  |
| ------------- | ----------------------------------------------------------- |
| **Header**    | Oberstes wiederkehrendes horizontales Textband einer Seite  |
| **Footer**    | Unterstes wiederkehrendes horizontales Textband einer Seite |
| **Furniture** | Sammelbegriff für Header und Footer                         |

Beide folgen demselben geometrischen Prinzip: einem stabilen horizontalen Band mit wiederkehrender Position.

---

## 4. Globale Mustererkennung

### 4.1 Kandidatenerzeugung

Für jede Seite werden potenzielle Kandidaten bestimmt:

* **Header:** oberes Viertel der Seite
* **Footer:** unteres Viertel der Seite
* alternativ: oberster bzw. unterster Textblock

Die Koordinaten werden auf die Seitenhöhe normalisiert:

```
y_rel = y / page_height
```

Dies ermöglicht eine dokumentübergreifend robuste Analyse.

---

### 4.2 Clustering der Kandidaten

Header und Footer treten auf vielen Seiten an nahezu identischen Positionen auf. Daher werden Kandidaten über alle Seiten hinweg aggregiert.

Kriterien:

* Häufigkeit des Auftretens
* geringe Streuung der Positionen
* konsistente Bandhöhe

Die Zone mit der höchsten Übereinstimmung wird als wahrscheinlicher Header bzw. Footer gewählt.

---

### 4.3 Statistische Annahme

Es ist äußerst unwahrscheinlich, dass Überschriften oder Bildunterschriften zufällig auf vielen Seiten exakt dieselbe Position einnehmen. Daher gilt:

> Das stabilste und am häufigsten auftretende horizontale Band entspricht mit hoher Wahrscheinlichkeit dem Header bzw. Footer.

---

## 5. Strukturelle Merkmale von Headern und Footern

Neben der Position weisen beide Furniture-Bereiche ähnliche strukturelle Eigenschaften auf.

### 5.1 Typische Inhalte

| Header                | Footer                   |
| --------------------- | ------------------------ |
| Kapitelname           | Seitenzahl               |
| Dokumenttitel         | Copyright-Hinweise       |
| Autor                 | Verlagsangaben           |
| Abschnittsbezeichnung | Fußnoten oder Referenzen |

---

### 5.2 Stabilität der Struktur

Stabile Signale sind:

* Anzahl der Textboxen
* Position innerhalb der Seite (links, mittig, rechts)
* Wiederkehrende Slot-Muster

Instabile Signale sind:

* konkrete Textinhalte
* Kapitelüberschriften
* variierende Breiten einzelner Boxen

Beispiele für stabile Muster:

| Muster                 | Bedeutung             |
| ---------------------- | --------------------- |
| links                  | Seitenzahl oder Titel |
| rechts                 | Seitenzahl            |
| links + rechts         | Titel und Seitenzahl  |
| links + mitte + rechts | komplexe Layouts      |

---

## 6. Lokale Seitenheuristik

Die seitenweise Analyse dient zwei Zwecken:

1. Verifikation global erkannter Zonen
2. Ersatzstrategie bei kurzen Dokumenten

### 6.1 Einsatzbereiche

| Dokumenttyp          | Strategie                       |
| -------------------- | ------------------------------- |
| Lange Dokumente      | globale Mustererkennung         |
| Kurze Dokumente      | lokale Heuristik                |
| Sehr kurze Dokumente | ausschließlich lokale Heuristik |

---

### 6.2 Kriterien der lokalen Entscheidung

Ein Header oder Footer wird auf einer Seite akzeptiert, wenn:

* er sich im erwarteten Seitenrand befindet,
* seine Dimensionen plausibel sind,
* er ausreichend Abstand zum Body-Text aufweist,
* seine Struktur typisch ist,
* er mit einem globalen Muster übereinstimmt (falls vorhanden).

---

## 7. Dokumentklassifikation nach Länge

Die Mindestanzahl an Seiten beeinflusst die Zuverlässigkeit der Statistik.

| Klasse     | Seitenanzahl | Strategie               |
| ---------- | ------------ | ----------------------- |
| Very Short | ≤ 5          | Lokale Heuristik        |
| Short      | 6–15         | Kombinierte Strategie   |
| Medium     | 16–50        | Überwiegend statistisch |
| Long       | > 50         | Statistisch robust      |

---

## 8. Entscheidungslogik

Die finale Entscheidung folgt einem hierarchischen Ansatz:

1. **Starkes globales Muster:** Nur Übereinstimmungen werden akzeptiert.
2. **Mittleres globales Muster:** Globales Matching mit lokalem Fallback.
3. **Kein globales Muster:** Lokale Heuristik entscheidet.

---

## 9. Qualitätsmetriken

Die Qualität eines Furniture-Bandes wird anhand folgender Faktoren bewertet:

* Häufigkeit des Auftretens
* Positionsstabilität
* Höhenkonsistenz
* strukturelle Ähnlichkeit
* Abstand zum Body-Text

---

## 10. Evaluationsstand

Aktuelle Ergebnisse der Geometrie-Evaluierung:

| Metrik          | Wert  |
| --------------- | ----- |
| Column Accuracy | 0.775 |
| Header Recall   | 0.913 |
| Footer F1-Score | 0.952 |

Die Footer-Erkennung ist nahezu optimal, während die Header-Erkennung aufgrund höherer struktureller Variabilität anspruchsvoller bleibt.

---

## 11. Implementierung in Atlas

Die Header- und Footer-Erkennung ist in folgenden Modulen implementiert:

```
src/atlas/parse/zones.py
src/atlas/parse/geometry.py
src/atlas/eval/geometry_eval.py
```

Zentrale Funktionen:

* `detect_repeated_furniture_bands`
* `decide_page_has_furniture`
* `build_page_layout_signatures`

---

## 12. Fazit

Die Furniture-Erkennung in Atlas basiert auf einem robusten, statistisch fundierten Ansatz:

* **Geometrisch:** horizontale Bänder
* **Statistisch:** wiederkehrende Muster
* **Strukturell:** stabile Layoutsignale
* **Adaptiv:** Kombination aus globaler und lokaler Analyse

Dieses Konzept bildet die Grundlage für ein zuverlässiges und skalierbares Document Understanding.

---

## Lizenz

Dieses Dokument ist Teil des Atlas-Projekts.

