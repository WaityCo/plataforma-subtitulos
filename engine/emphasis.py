"""Énfasis por significado: puntaje de palabras y elección de frases según presets/emphasis_lexicon.json.

Cada frase lleva como mucho una unidad enfatizada: una palabra o un compuesto de dos palabras
contiguas. Nunca se enfatizan stopwords (presets/stopwords.json), contracciones con apóstrofe ni
palabras vacías. select_emphasis() ordena las frases por su mejor puntaje y marca las primeras hasta
cubrir la fracción pedida; las frases con marca manual ya cuentan. El formato del léxico está en la
clave "_nota" de ese archivo.
"""

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from engine.stopwords import is_stopword

LEXICON_PATH = Path(__file__).resolve().parent.parent / "presets" / "emphasis_lexicon.json"
COMPOUND_SIZE = 2
DIGITS_CATEGORY = "cantidad"
_EDGE = re.compile(r"^\W+|\W+$")  # puntuación y comillas de los extremos; los guiones internos quedan
_QUOTES = "\"“”«»"
_APOSTROPHES = "'’"


@dataclass(frozen=True)
class Lexicon:
    words: dict  # clave normalizada -> (peso, categoría)
    compounds: dict  # "palabra palabra" -> (peso, categoría)
    quote_weight: int
    digits_weight: int


@dataclass(frozen=True)
class Unit:
    score: int
    start: int
    end: int  # exclusivo


def normalize(text):
    """Minúsculas, sin tildes y sin puntuación de los extremos. Un apóstrofe interno se conserva."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _EDGE.sub("", plain)


@lru_cache(maxsize=None)
def load_lexicon(path=LEXICON_PATH):
    """Lee el léxico una vez por ruta. Lanza ValueError si una entrada no cumple el formato."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    categories = raw.get("categorias")
    if not isinstance(categories, dict) or not categories:
        raise ValueError(f"{path}: falta el objeto 'categorias'")
    words, compounds = {}, {}
    for name, body in categories.items():
        weight = body.get("peso")
        if not (isinstance(weight, int) and not isinstance(weight, bool) and 1 <= weight <= 10):
            raise ValueError(f"{path}: el peso de '{name}' debe ser un entero de 1 a 10")
        for lang_items in body.get("palabras", {}).values():
            for item in lang_items:
                key = normalize(item)
                if not key or len(key.split()) != 1:
                    raise ValueError(f"{path}: '{item}' en '{name}' debe ser una sola palabra")
                _keep_heaviest(words, key, (weight, name))
        for lang_items in body.get("compuestos", {}).values():
            for item in lang_items:
                parts = normalize(item).split()
                if len(parts) != COMPOUND_SIZE:
                    raise ValueError(f"{path}: el compuesto '{item}' en '{name}' debe tener {COMPOUND_SIZE} palabras")
                if any(is_stopword(part) for part in parts):
                    raise ValueError(f"{path}: el compuesto '{item}' tiene una stopword")
                _keep_heaviest(compounds, " ".join(parts), (weight, name))
    digits = categories.get(DIGITS_CATEGORY, {}).get("peso", 0)
    return Lexicon(words=words, compounds=compounds, quote_weight=int(raw.get("peso_comillas", 0)),
                   digits_weight=int(digits))


def _keep_heaviest(table, key, entry):
    if key not in table or entry[0] > table[key][0]:
        table[key] = entry


def _usable(text, key):
    """False para vacíos, stopwords y contracciones: nunca se enfatizan."""
    if not key or is_stopword(key):
        return False
    return not any(char in text for char in _APOSTROPHES)


def _token_weight(text, key, lexicon):
    weight = lexicon.digits_weight if key.isdigit() else 0
    entry = lexicon.words.get(key)
    if entry:
        weight = max(weight, entry[0])
    opening = text.lstrip()[:1]
    if opening and opening in _QUOTES and len(key) >= 2:
        weight = max(weight, lexicon.quote_weight)
    return weight


def units(texts, lexicon=None):
    """Unidades puntuables de una frase, palabras y compuestos. texts son las palabras en orden.

    Una palabra vacía (p. ej. marcada emph: false) no puntúa ni forma compuestos.
    """
    lexicon = lexicon or load_lexicon()
    keys = [normalize(text) for text in texts]
    usable = [_usable(text, key) for text, key in zip(texts, keys)]
    found = []
    for index, (text, key) in enumerate(zip(texts, keys)):
        weight = _token_weight(text, key, lexicon) if usable[index] else 0
        if weight:
            found.append(Unit(weight, index, index + 1))
    for index in range(len(texts) - COMPOUND_SIZE + 1):
        span = range(index, index + COMPOUND_SIZE)
        if all(usable[i] for i in span):
            entry = lexicon.compounds.get(" ".join(keys[i] for i in span))
            if entry:
                found.append(Unit(entry[0], index, index + COMPOUND_SIZE))
    return found


def best_unit(texts, lexicon=None):
    """Unidad de mayor puntaje; en empate gana la más corta (una palabra) y luego la primera. None si no hay."""
    found = units(texts, lexicon)
    if not found:
        return None
    return max(found, key=lambda unit: (unit.score, -(unit.end - unit.start), -unit.start))


def select_emphasis(phrases, ratio=None, marked=(), lexicon=None):
    """Una unidad (inicio, fin exclusivo) o None por frase. phrases es una lista de listas de textos.

    Sin ratio se marcan todas las frases con puntaje. Con ratio se marcan las de mayor puntaje hasta
    llegar a round(ratio * frases), contando las de marked (índices con énfasis manual, que no se tocan).
    """
    lexicon = lexicon or load_lexicon()
    marked = set(marked)
    best = [best_unit(texts, lexicon) for texts in phrases]
    order = sorted(
        (index for index, unit in enumerate(best) if unit is not None and index not in marked),
        key=lambda index: (-best[index].score, index),
    )
    if ratio is None:
        take = len(order)
    else:
        take = max(0, math.floor(ratio * len(phrases) + 0.5) - len(marked))
    chosen = [None] * len(phrases)
    for index in order[:take]:
        chosen[index] = (best[index].start, best[index].end)
    return chosen


def select_emphasis_multi(phrases, ratio=None, marked=(), lexicon=None, max_words=None):
    """Unidades enfatizadas por frase: una lista de (inicio, fin exclusivo) por frase, vacía si no lleva.

    Sin max_words, o con max_words 1, cada frase elegida lleva solo su mejor unidad, igual que
    select_emphasis. Con max_words N >= 2, la frase elegida suma las demás unidades que no se solapen, de
    mayor puntaje, mientras el total no pase de N palabras. Las frases que elige ratio no cambian.
    """
    lexicon = lexicon or load_lexicon()
    chosen = select_emphasis(phrases, ratio, marked=marked, lexicon=lexicon)
    if max_words is None or max_words < 2:
        return [[] if unit is None else [unit] for unit in chosen]
    result = []
    for texts, unit in zip(phrases, chosen):
        if unit is None:
            result.append([])
            continue
        picked = [unit]
        used = set(range(*unit))
        budget = max_words - (unit[1] - unit[0])
        for other in sorted(units(texts, lexicon), key=lambda found: (-found.score, found.start)):
            span = set(range(other.start, other.end))
            size = other.end - other.start
            if span & used or size > budget:
                continue
            picked.append((other.start, other.end))
            used |= span
            budget -= size
        result.append(sorted(picked))
    return result
