#!/usr/bin/env python3
"""
Vortraining von CharLM-Modellen aus Wiktionary-Frequenzlisten.

Quellen (alle CC0/frei):
  - https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/
    content/2018/{lang}/{lang}_50k.txt
    Format: "word count" pro Zeile

Trainiert auf Top-50k Wörter pro Sprache.
Speichert in src/atlas/semantic/data/charlm/{lang}.json
"""
import sys, json, math, re, urllib.request
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from atlas.semantic.charlm import CharLM

OUTPUT_DIR = Path(__file__).parent.parent / "src/atlas/semantic/data/charlm"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = ("https://raw.githubusercontent.com/hermitdave/FrequencyWords"
            "/master/content/2018/{lang}/{lang}_50k.txt")

# ISO 639-1 → FrequencyWords Ordnername
# Europäische Sprachen + wichtige Wissenschaftssprachen
LANGUAGES = {
    # Germanisch
    "de": "de",    # Deutsch
    "en": "en",    # Englisch
    "nl": "nl",    # Niederländisch
    "sv": "sv",    # Schwedisch
    "da": "da",    # Dänisch
    "no": "no",    # Norwegisch
    "is": "is",    # Isländisch
    "af": "af",    # Afrikaans
    # Romanisch
    "fr": "fr",    # Französisch
    "it": "it",    # Italienisch
    "es": "es",    # Spanisch
    "pt": "pt",    # Portugiesisch
    "ro": "ro",    # Rumänisch
    "ca": "ca",    # Katalanisch
    "gl": "gl",    # Galizisch
    # Slawisch
    "pl": "pl",    # Polnisch
    "cs": "cs",    # Tschechisch
    "sk": "sk",    # Slowakisch
    "sl": "sl",    # Slowenisch
    "hr": "hr",    # Kroatisch
    "bs": "bs",    # Bosnisch
    "sr": "sr",    # Serbisch
    "bg": "bg",    # Bulgarisch
    "uk": "uk",    # Ukrainisch
    "ru": "ru",    # Russisch
    "mk": "mk",    # Mazedonisch
    # Baltisch
    "lt": "lt",    # Litauisch
    "lv": "lv",    # Lettisch
    # Finnougrisch
    "fi": "fi",    # Finnisch
    "hu": "hu",    # Ungarisch
    "et": "et",    # Estnisch
    # Andere europäisch
    "el": "el",    # Griechisch
    "sq": "sq",    # Albanisch
    "eu": "eu",    # Baskisch
    "hy": "hy",    # Armenisch
    "ka": "ka",    # Georgisch
    # Wissenschaftssprachen
    "ar": "ar",    # Arabisch
    "he": "he",    # Hebräisch
    "tr": "tr",    # Türkisch
    "fa": "fa",    # Persisch
    "hi": "hi",    # Hindi
    "id": "id",    # Indonesisch (Malay-Basis, nah an Swahili)
    "ms": "ms",    # Malay
    "zh_cn": "zh_cn",  # Chinesisch
    "ja": "ja",    # Japanisch
    "ko": "ko",    # Koreanisch
    "vi": "vi",    # Vietnamesisch
}

# Swahili: nicht in FrequencyWords — separater Download
# https://raw.githubusercontent.com/stopwords-iso/stopwords-sw/master/stopwords-sw.txt
# Für vollständiges SW-Modell: Wiktionary-Frequenzliste nutzen
SWAHILI_WORDS = (
    "na ya wa kwa ni za au pia sana hata bali lakini kama kuwa "
    "nyumba mji mtu watu mwaka siku wiki mwezi muda "
    "kazi shule hospitali dawa chakula maji ardhi "
    "historia utamaduni elimu sayansi sanaa muziki "
    "jengo nyumba ukuta dari paa mlango dirisha "
    "mbao nguzo boriti paa ukuta msingi"
)

# Latein: kleine kuratierte Liste
LATIN_WORDS = (
    "et in de ad ex cum per pro ab ob sub inter ante post super trans "
    "contra sine sed aut vel nec non qui quae quod est sunt esse hoc "
    "ille illa illud hic haec homo hominis rex regis urbs urbis terra "
    "aqua ignis ventus silva porta via dies nox tempus annus vita mors "
    "pater mater filius filia dominus servus miles bellum pax amor "
    "arbor domus villa templum forum populus senatus consul imperator "
    "deus dea caelum terra mare flumen mons campus ager opus carmen "
    "liber verbum vox mens corpus anima virtus gloria fortuna natura "
    "historia philosophia rhetorica grammatica mathematica astronomia"
)


def download_wordlist(lang: str) -> list[str]:
    """Lädt Frequenzliste von hermitdave/FrequencyWords."""
    url = BASE_URL.format(lang=lang)
    print(f"  Downloading {url}...", end=" ", flush=True)
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            content = r.read().decode("utf-8", errors="ignore")
        words = []
        for line in content.splitlines():
            parts = line.strip().split()
            if parts:
                word = parts[0].lower()
                # Nur echte Wörter (keine Zahlen, URLs)
                if re.match(r'^[a-záéíóúàâäèêëîïôùûüÄÖÜß\-]{3,}$', word):
                    words.append(word)
        print(f"{len(words)} Wörter")
        return words[:50_000]
    except Exception as e:
        print(f"Fehler: {e}")
        return []


def train_and_save(lang: str, words: list[str]) -> None:
    lm = CharLM(n=3)
    # Jedes Wort mehrfach trainieren simuliert Häufigkeit
    text = " ".join(words)
    lm.train(text)
    out = OUTPUT_DIR / f"{lang}.json"
    lm.save(out)
    print(f"  [{lang}] {lm._trained_words} Wörter → {out}")


print("=== CharLM Vortraining ===\n")

for lang in LANGUAGES:
    print(f"\n{lang.upper()}:")
    words = download_wordlist(lang)
    if words:
        train_and_save(lang, words)

# Latein aus kuratierter Liste
print("\nLA:")
lm_la = CharLM(n=3)
lm_la.train(LATIN_WORDS * 20)
out_la = OUTPUT_DIR / "la.json"
lm_la.save(out_la)
print(f"  [la] {lm_la._trained_words} Wörter → {out_la}")

# Swahili aus kuratierter Liste
print("\nSW (Swahili — kuratiert):")
lm_sw = CharLM(n=3)
lm_sw.train(SWAHILI_WORDS * 30)
out_sw = OUTPUT_DIR / "sw.json"
lm_sw.save(out_sw)
print(f"  [sw] {lm_sw._trained_words} Wörter → {out_sw}")

print(f"\nFertig. {len(list(OUTPUT_DIR.glob('*.json')))} Modelle in:", OUTPUT_DIR)
