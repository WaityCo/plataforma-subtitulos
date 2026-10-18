"""Palabras vacías en español e inglés. El énfasis automático nunca elige una de ellas.

La lista vive en presets/stopwords.json: el motor y la API (/api/stopwords) leen el mismo archivo.
"""

import json
import unicodedata
from pathlib import Path

STOPWORDS_PATH = Path(__file__).resolve().parent.parent / "presets" / "stopwords.json"


def _normalize(text):
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def stopword_lists():
    """Listas {"es": [...], "en": [...]} tal como están en presets/stopwords.json."""
    return json.loads(STOPWORDS_PATH.read_text(encoding="utf-8"))


STOPWORDS = frozenset(_normalize(word) for words in stopword_lists().values() for word in words)


def is_stopword(word):
    """True si la palabra está en la lista ES+EN, sin importar mayúsculas ni tildes."""
    return _normalize(word) in STOPWORDS
