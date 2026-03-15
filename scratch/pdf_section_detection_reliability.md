# Wie sicher ist Abschnittserkennung im PDF?

## Die ehrliche Antwort zuerst

Nicht sehr sicher — wenn man "sicher" als zuverlässig über alle Dokumenttypen hinweg versteht.

Die Frage nach der Sicherheit ist eigentlich drei Fragen in einer:
1. Wie zuverlässig sind die **Signale** (Schrift, Abstand, Position)?
2. Wie stabil sind die **Muster** (Titelei, Referenzen, Abstract) über Dokumenttypen?
3. Wo liegt die **fundamentale Grenze** — was kein Algorithmus lösen kann?

---

## Signalqualität nach Dokumenttyp

Die Zuverlässigkeit hängt fast vollständig davon ab, *wie* das Dokument erzeugt wurde.

| Dokumenttyp | Signalqualität | Erreichbare Genauigkeit |
|---|---|---|
| LaTeX-Paper (PDF/A) | Exzellent — klare Größenhierarchie, exakte Abstände | ~90–95 % |
| Word-Export mit Formatvorlagen | Gut — Stile einheitlich, Abstände manchmal ungleichmäßig | ~80–90 % |
| Word-Export ohne Formatvorlagen | Schlecht — alles gleich groß, nur Fettdruck als Signal | ~50–65 % |
| InDesign / professioneller Satz | Variabel — layoutabhängig, oft Mehrspaltig | ~60–80 % |
| Scan + OCR | Sehr schlecht — Koordinaten ungenau, Artefakte | ~40–60 % |
| PowerPoint-Export | Unbrauchbar für Fließtext — Folientitel ≠ Kapitelstruktur | ~30–50 % |
| Behördendokument / Formular | Individuell — keine Konvention | ~50–70 % |

**Die Kernaussage:** Algorithmen erkennen Konventionen, nicht Semantik. Wer LaTeX benutzt, folgt implizit `\section`, `\subsection` — das erzeugt messbare typografische Hierarchien. Wer in Word alles manuell formatiert, hinterlässt keine maschinenlesbare Struktur.

---

## Abschnitte nach Erkennbarkeit

### Sehr gut erkennbar (>85 % über alle Typen)

**Kopf- und Fußzeilen**
Das einfachste Problem. Position allein reicht: y < 10 % oder y > 90 % der Seite, konstant wiederholend, kurzer Text. Fehlerquelle: Dokumente mit sehr kurzem Inhalt, bei denen Haupttext in die Randzone fällt.

**Seitenzahlen**
Reine Ziffern, Fußposition, oft zentriert. Regex `^\d+$` mit Positionsfilter trifft nahezu immer.

**Referenzliste / Literaturverzeichnis**
Starkes Signal: Abschnittsüberschrift ("References", "Literatur", "Bibliography"), danach Zeilen mit spezifischen Mustern — Jahreszahlen in Klammern, DOI-Nummern, Autorenlisten mit Komma-getrennten Nachnamen. Der Beginn ist leicht zu finden; das Ende (letzter Eintrag vs. Anhang) ist schwieriger.

```python
REFERENCE_HEADERS = re.compile(
    r"^(references?|bibliography|literatur(verzeichnis)?|"
    r"quellenverzeichnis|works cited)$",
    re.IGNORECASE
)

REFERENCE_ENTRY = re.compile(
    r"(\[\d+\]|^\d+\.)\s"           # [1] oder 1.
    r"|[A-Z][a-z]+,\s[A-Z]\."       # Nachname, V.
    r"|\(\d{4}\)"                    # (2019)
    r"|doi:|https?://|arxiv"
)
```

### Gut erkennbar (70–85 %)

**Abstract**
Fast immer explizit benannt ("Abstract", "Zusammenfassung", "Summary"). Typisch: ein einziger Block ohne Untergliederung, oft auf Seite 1. Schwieriger bei Dokumenten, die den Abstract ohne Überschrift direkt nach dem Titel beginnen.

**Nummerierte Überschriften**
`1.`, `2.1`, `3.2.4` — das Muster ist eindeutig. Hierarchie folgt automatisch aus der Nummerierung. Fehlerquelle: Listenpunkte, die wie Überschriften nummeriert sind.

```python
NUMBERED_HEADING = re.compile(
    r"^(\d+\.){1,3}\s+[A-ZÄÖÜ\w]"  # 1. Einleitung / 2.3.1 Methodik
    r"|^[A-Z]\.\s+[A-ZÄÖÜ]"         # A. Einleitung
    r"|^§\s*\d+"                     # § 3
)
```

**Anhänge / Appendix**
Klares Label, oft am Dokumentende, manchmal mit Buchstabennummerierung (Appendix A, B). Schwieriger wenn Anhänge ohne Label nahtlos folgen.

### Mittel erkennbar (55–70 %)

**Titelei (Seite 1–2)**
Titel ist gut erkennbar (größte Schrift). Autoren sind schwierig: kein universelles Format, oft mit Institutionen vermischt, manchmal Fußnotenzeichen (†, *, 1) eingefügt. Affiliationen sind kaum von Fußnoten zu unterscheiden.

Das eigentliche Problem: Zwischen Titel und Abstract liegt auf Seite 1 eine Grauzone — Untertitel, Autoren, Affiliation, Datum, Konferenzname — all das hat ähnliche Schriftgröße und ähnlichen Abstand.

**Fußnoten**
Kleinere Schrift, Seitenende, oft mit Ziffer eingeleitet. Aber: Bildunterschriften sehen identisch aus. Unterschied liegt im inhaltlichen Muster (Fußnote: Erklärung/Quelle; Caption: beginnt mit "Abb."), nicht im Layout.

**Methoden / Results / Discussion**
Bei wissenschaftlichen Artikeln durch IMRaD-Struktur gut erkennbar. Bei allen anderen Dokumenttypen: kein universelles Muster. Ein Bericht hat andere Abschnittsnamen als ein Vertrag als ein Handbuch.

### Schlecht erkennbar (<55 %)

**Unnummerierte, unformatierte Überschriften**
Word-Dokumente ohne Formatvorlagen: fett, gleiche Schriftgröße wie Fließtext. Das einzige Signal ist `is_bold + short_line + space_before`. Das ist schwach — Hervorhebungen im Fließtext haben dieselben Merkmale.

**Einleitung ohne Label**
Viele Texte beginnen direkt mit Fließtext nach dem Abstract — ohne "Introduction"-Überschrift. Algorithmus kann den Einleitungstext nicht von einem beliebigen ersten Abschnitt unterscheiden.

**Mehrstufige Listen in Fließtext**
Liste vs. Aufzählung vs. nummerierter Absatz vs. nummerierte Überschrift: oft nicht unterscheidbar ohne Semantik.

**Zusammenfassung am Dokumentende**
"Summary", "Conclusion", "Fazit" — das Label ist erkennbar. Aber: Ist es eine Zusammenfassung des ganzen Dokuments oder eines Unterabschnitts? Das ist eine semantische Frage, keine typografische.

---

## Die fundamentale Grenze

Drei Probleme sind **nicht algorithmisch lösbar** — sie erfordern Sprachverständnis:

**1. Gleichförmige Dokumente**
Ein Anwaltsschriftsatz, ein Roman, ein Gutachten: alles gleich groß, gleicher Abstand, kein Fettdruck. Die Abschnitte sind semantisch definiert ("Sachverhalt", "Rechtliche Würdigung"), nicht typografisch. Kein Größen- oder Abstandsalgorithmus hilft hier.

**2. Implizite Struktur**
"Der nächste Punkt betrifft die Methodik." — das ist eine Überschrift im Fließtext. Kein Algorithmus erkennt das ohne Sprachverständnis.

**3. Dokumentspezifische Konventionen**
Österreichische Behördenbriefe folgen anderen Konventionen als WHO-Berichte als US-Gerichtsdokumente als DIN-Normen. Kein universeller Regelkatalog deckt das ab.

---

## Drei-Stufen-Strategie

### Stufe 1: Regelbasiert (schnell, deterministisch)

Für die erkennbaren Fälle: Kopfzeilen, Seitenzahlen, Referenzen, nummerierte Überschriften. Präzision ~85 %, Recall ~70 %. Gut genug für strukturierte wissenschaftliche Dokumente.

```python
SECTION_PATTERNS = {
    "abstract":    re.compile(r"^(abstract|zusammenfassung|summary)$", re.I),
    "intro":       re.compile(r"^(1\.?\s*)?(introduction|einleitung|einführung)$", re.I),
    "methods":     re.compile(r"^(\d+\.?\s*)?(methods?|methodik|material(ien)?\s*(und|&)\s*methoden?)$", re.I),
    "results":     re.compile(r"^(\d+\.?\s*)?(results?|ergebnisse)$", re.I),
    "discussion":  re.compile(r"^(\d+\.?\s*)?(discussion|diskussion)$", re.I),
    "conclusion":  re.compile(r"^(\d+\.?\s*)?(conclusions?|fazit|zusammenfassung|schluss(folgerung)?)$", re.I),
    "references":  re.compile(r"^(references?|bibliography|literatur(verzeichnis)?)$", re.I),
    "appendix":    re.compile(r"^(appendix|anhang)\s*[A-Z]?$", re.I),
    "keywords":    re.compile(r"^keywords?:|schlüsselwörter:", re.I),
}

def detect_named_sections(lines: list) -> list:
    """Markiert Zeilen, die bekannte Abschnittsbezeichnungen tragen."""
    for line in lines:
        text = line.text.strip()
        for section_name, pattern in SECTION_PATTERNS.items():
            if pattern.match(text):
                line.role    = "section_header"
                line.section = section_name
                break
    return lines
```

### Stufe 2: ML-basiert (robuster, trainierbar)

Ein trainiertes Modell (z.B. LayoutLM, oder ein einfacher Gradient-Boosting-Classifier) auf dem Feature-Vektor aus dem vorherigen Dokument. Präzision ~80–88 % auf bekannten Dokumentklassen.

Der entscheidende Vorteil: Das Modell lernt dokumenttyp-spezifische Schwellenwerte, statt universelle Regeln anzuwenden.

```python
# Feature-Vektor für ML (aus LineFeatures)
def to_feature_vector(lf) -> list[float]:
    return [
        lf.size_ratio,
        float(lf.is_bold),
        float(lf.is_italic),
        float(lf.is_all_caps),
        float(lf.is_centered),
        lf.space_ratio,
        lf.line_width_ratio,
        min(lf.word_count / 20.0, 1.0),   # normiert
        float(lf.ends_with_period),
        float(lf.starts_with_number),
        float(lf.starts_with_bullet),
        lf.y_rel,
        float(lf.page == 1),
        float(lf.page <= 2),
    ]
```

### Stufe 3: LLM (für semantische Fälle)

Wenn Stufe 1 und 2 keine Struktur liefern — oder wenn man semantische Abschnitte braucht, nicht nur typografische.

Der Trick: Nicht das ganze Dokument schicken. Stattdessen nur die **Kandidatenzeilen** — alle Zeilen, die der Algorithmus für Überschriften hält oder nicht klassifizieren konnte.

```python
import anthropic, json, re

def llm_classify_candidates(candidates: list[str], doc_type: str) -> dict:
    """
    Schickt Kandidatenzeilen an Claude zur semantischen Klassifizierung.
    Günstiger als das gesamte Dokument, präziser als Regelwerk.
    """
    client  = anthropic.Anthropic()
    listing = "\n".join(f"{i}: {t}" for i, t in enumerate(candidates))

    prompt = f"""Dies sind Textzeilen aus einem {doc_type}-Dokument, die möglicherweise Abschnittsüberschriften sind.

Klassifiziere jede Zeile. Mögliche Rollen:
title, subtitle, author, abstract_header, section_header, subsection_header,
body_text, list_item, caption, footnote, reference_entry, page_number,
header_footer, keyword_line, date, affiliation, unknown

Antworte nur als JSON: {{"0": "role", "1": "role", ...}}

Zeilen:
{listing}"""

    msg = client.messages.create(
        model    = "claude-sonnet-4-20250514",
        max_tokens = 1024,
        messages = [{"role": "user", "content": prompt}]
    )
    raw = re.sub(r"```json\s*|\s*```", "", msg.content[0].text).strip()
    return json.loads(raw)
```

---

## Realistischer Genauigkeitsrahmen

| Abschnitt | Regelbasiert | + ML | + LLM |
|---|---|---|---|
| Kopfzeile / Fußzeile | 95 % | 96 % | 97 % |
| Seitenzahlen | 98 % | 98 % | 98 % |
| Referenzliste (Start) | 88 % | 91 % | 95 % |
| Abstract | 82 % | 87 % | 93 % |
| Nummerierte Überschriften | 85 % | 90 % | 93 % |
| Titelei (Titel) | 80 % | 85 % | 92 % |
| Titelei (Autoren) | 55 % | 68 % | 85 % |
| IMRaD-Abschnitte (benannt) | 83 % | 87 % | 94 % |
| Unnummerierte Überschriften | 45 % | 62 % | 80 % |
| Fußnoten vs. Captions | 60 % | 72 % | 88 % |
| Implizite Struktur | 15 % | 35 % | 70 % |

*Schätzwerte auf gut formatierten wissenschaftlichen und technischen Dokumenten. Bei Scans, behördlichen Dokumenten und unformatierten Word-Exports deutlich niedriger.*

---

## Praktische Empfehlung

Für die meisten Anwendungsfälle reicht eine **hybride Pipeline**:

```
Regelbasiert (Stufe 1)
    → deckt ~70 % der Fälle mit hoher Präzision ab

Verbleibende Kandidaten → ML-Classifier (Stufe 2)
    → bringt weitere ~15 % auf akzeptable Genauigkeit

Unklare Fälle → LLM (Stufe 3)
    → für die semantisch schwierigen 15 %

Menschliche Kontrolle
    → für Dokumente mit geschäftskritischer Strukturinterpretation
```

Den LLM für alles einzusetzen ist möglich, aber teuer und langsam. Ihn gar nicht einzusetzen bedeutet, bei impliziter Struktur zu scheitern. Die Stufenarchitektur gibt das Beste aus beiden Welten.
