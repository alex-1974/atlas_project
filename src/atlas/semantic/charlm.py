"""
atlas.semantic.charlm

Zeichen-Niveau Sprachmodell für Keyword-Qualitätsbewertung.

Ein n-Gramm Modell lernt welche Zeichenfolgen in einer Sprache
normal sind. Unbekannte/unmögliche Wörter bekommen niedrige Scores.

Vorteil gegenüber Regelsets:
- Keine manuellen Vokal/Konsonant-Regeln
- Passt sich an Fachsprache des Korpus an
- Sprachagnostisch trainierbar

Training:
    lm = CharLM.train_from_catalog(conn, lang="de")
    lm.save(path)

Nutzung:
    lm = CharLM.load(path)
    score = lm.score("Hallenhaus")   # ~ -15
    score = lm.score("MTTQU")        # ~ -45  (sehr unwahrscheinlich)
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

# Mindest-Score Schwellenwert: Wörter mit score < threshold werden gefiltert.
# Kalibriert auf bekannte gute/schlechte Wörter.
_DEFAULT_THRESHOLD = -6.5

# Minimales Trainingskorpus (Wörter) für verlässliche Schätzungen
_MIN_TRAINING_WORDS = 500


class CharLM:
    """
    Zeichen-Trigramm Sprachmodell mit Laplace-Glättung.

    score(word) gibt die mittlere Log-Wahrscheinlichkeit der
    Zeichentrigramme zurück. Höhere Werte = plausibler.
    """

    def __init__(self, n: int = 3):
        self.n = n
        self.counts: dict[str, int] = defaultdict(int)
        self.context_counts: dict[str, int] = defaultdict(int)
        self._trained_words: int = 0

    def train(self, text: str) -> None:
        """Trainiert das Modell auf einem Text."""
        # Wörter extrahieren (nur Buchstaben)
        words = re.findall(r"[^\W\d_]{3,}", text.lower())
        for word in words:
            padded = "^" + word + "$"
            for i in range(len(padded) - self.n + 1):
                ngram   = padded[i:i + self.n]
                context = ngram[:-1]
                self.counts[ngram] += 1
                self.context_counts[context] += 1
        self._trained_words += len(words)

    def score(self, word: str) -> float:
        """
        Log-Wahrscheinlichkeit eines Wortes.
        Höher = plausibler. Typisch: echte Wörter -10 bis -25,
        OCR-Müll -35 bis -60.
        """
        if not word or not self.counts:
            return -100.0

        padded = "^" + word.lower() + "$"
        log_prob = 0.0
        vocab_size = len(self.counts)

        for i in range(len(padded) - self.n + 1):
            ngram   = padded[i:i + self.n]
            context = ngram[:-1]
            # Laplace-Glättung
            count   = self.counts.get(ngram, 0) + 1
            ctx_cnt = self.context_counts.get(context, 0) + vocab_size
            log_prob += math.log(count / ctx_cnt)

        # Normiert auf Wortlänge für Vergleichbarkeit
        n_grams = len(padded) - self.n + 1
        return log_prob / max(1, n_grams) if n_grams > 0 else -100.0

    def is_plausible(
        self,
        word: str,
        threshold: float = _DEFAULT_THRESHOLD,
    ) -> bool:
        """True wenn Wort phonotaktisch plausibel ist."""
        if self._trained_words < _MIN_TRAINING_WORDS:
            return True  # Zu wenig Training — nicht filtern
        return self.score(word) >= threshold

    def save(self, path: Path) -> None:
        """Speichert Modell als JSON."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "n": self.n,
            "trained_words": self._trained_words,
            "counts": dict(self.counts),
            "context_counts": dict(self.context_counts),
        }
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "CharLM":
        """Lädt Modell aus JSON."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        lm = cls(n=data["n"])
        lm.counts = defaultdict(int, data["counts"])
        lm.context_counts = defaultdict(int, data["context_counts"])
        lm._trained_words = data.get("trained_words", 0)
        return lm

    @classmethod
    def train_from_catalog(
        cls,
        conn: sqlite3.Connection,
        lang: str,
        n: int = 3,
    ) -> "CharLM":
        """
        Trainiert CharLM aus Section-Texten des Katalogs.

        Nutzt section_titles + FTS body_text für Sprache `lang`.
        Bootstrapping: der Katalog selbst ist das Trainingskorpus.
        """
        lm = cls(n=n)

        # Section-Titel der richtigen Sprache
        rows = conn.execute(
            """
            SELECT st.title
            FROM du_section_tree st
            JOIN documents d ON d.document_id = st.document_id
            WHERE d.language = ? AND st.title IS NOT NULL
            """,
            (lang,),
        ).fetchall()

        for row in rows:
            if row[0]:
                lm.train(row[0])

        # FTS body_text
        rows = conn.execute(
            """
            SELECT f.body_text
            FROM documents_fts f
            JOIN documents d ON d.document_id = f.document_id
            WHERE d.language = ? AND f.body_text IS NOT NULL
            """,
            (lang,),
        ).fetchall()

        for row in rows:
            if row[0]:
                # Nur ersten 2000 Zeichen pro Dokument
                lm.train(row[0][:2000])

        return lm


# ---------------------------------------------------------------------------
# Modell-Cache (Singleton pro Sprache)
# ---------------------------------------------------------------------------

_MODEL_CACHE: dict[str, CharLM] = {}
_MODEL_DIR   = Path.home() / ".atlas" / "charlm"


def get_model(lang: str, conn: sqlite3.Connection | None = None) -> CharLM | None:
    """
    Gibt ein CharLM-Modell für eine Sprache zurück.

    Reihenfolge:
    1. In-Memory Cache
    2. Gespeichertes Modell in ~/.atlas/charlm/
    3. Training aus Katalog (wenn conn vorhanden)
    4. None wenn nicht möglich
    """
    if lang in _MODEL_CACHE:
        return _MODEL_CACHE[lang]

    model_path = _MODEL_DIR / f"{lang}.json"
    if model_path.exists():
        try:
            lm = CharLM.load(model_path)
            if lm._trained_words >= _MIN_TRAINING_WORDS:
                _MODEL_CACHE[lang] = lm
                return lm
        except Exception:
            pass

    if conn is not None:
        lm = CharLM.train_from_catalog(conn, lang)
        if lm._trained_words >= _MIN_TRAINING_WORDS:
            lm.save(model_path)
            _MODEL_CACHE[lang] = lm
            return lm

    return None


def train_all_languages(conn: sqlite3.Connection) -> dict[str, int]:
    """
    Trainiert CharLM-Modelle für alle Sprachen im Katalog.
    Gibt {lang: trained_words} zurück.
    """
    langs = [
        row[0] for row in conn.execute(
            "SELECT DISTINCT language FROM documents "
            "WHERE language IS NOT NULL AND language != ''"
        ).fetchall()
    ]

    results = {}
    for lang in langs:
        lm = CharLM.train_from_catalog(conn, lang)
        if lm._trained_words >= _MIN_TRAINING_WORDS:
            model_path = _MODEL_DIR / f"{lang}.json"
            lm.save(model_path)
            _MODEL_CACHE[lang] = lm
            results[lang] = lm._trained_words

    return results
