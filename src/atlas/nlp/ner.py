from __future__ import annotations

import spacy

_nlp_de = None
_nlp_en = None


def _load_de():
    global _nlp_de
    if _nlp_de is None:
        _nlp_de = spacy.load("de_core_news_sm")
    return _nlp_de


def _load_en():
    global _nlp_en
    if _nlp_en is None:
        _nlp_en = spacy.load("en_core_web_sm")
    return _nlp_en


def extract_person_entities(text: str) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    for loader, labels in (
        (_load_de, {"PER"}),
        (_load_en, {"PERSON"}),
    ):
        try:
            doc = loader()(text)
        except Exception:
            continue

        for ent in doc.ents:
            if ent.label_ not in labels:
                continue

            value = " ".join(ent.text.split()).strip()
            if not value:
                continue
            if value in seen:
                continue

            seen.add(value)
            results.append(value)

    return results
