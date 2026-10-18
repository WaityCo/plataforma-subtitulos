"""Evaluación de la segmentación de ken_remedie contra el gold.

Dos conjuntos. (a) El gold reconstruido: 108 frases con tiempos repartidos por caracteres, sin pausas, así que
mide solo las reglas de texto. (b) Los dos clips con palabras de Whisper y tiempos reales, así que mide las reglas
y las pausas. Las palabras de (b) son las que guarda tests/fixtures/ken_remedie/whisper/*.json.

Métricas: F1 de fronteras de frase, reparto de palabras por frase (1, 2, 3, 4 y 5 o más) y mediana de duración.
Una frontera solo se compara donde la palabra del gold y la de Whisper casan. Las que caen en palabras sin pareja
(Whisper las inventa u omite) no cuentan ni como acierto ni como fallo.
"""

import difflib
import json
import re
import statistics
from collections import Counter
from pathlib import Path

from engine.layout import build_segments
from engine.styles import resolve
from engine.timeline import gold_phrases

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ken_remedie"
GOLD = FIXTURES / "timelines" / "gold" / "DekXWuPh2T-_gold.json"
WHISPER = FIXTURES / "whisper"
# Ventanas de los clips dentro del reel: desplazamiento del clip y duración en segundos.
CLIPS = {
    "clip19": {"file": "clip19_small.json", "offset": 19.4, "duration": 8.0},
    "clip84": {"file": "clip84_small.json", "offset": 84.0, "duration": 9.0},
}
# 03, en % de frases: 1 palabra 25 | 2 palabras 22 a 31 | 3 palabras 29 a 37 | 4 palabras 13 a 14 | 5 o más 1 a 2.
REFERENCE_SHARES = {1: 25.0, 2: 26.5, 3: 33.0, 4: 13.5, 5: 1.5}
DISTRIBUTION_TOLERANCE = 10.0
DISTRIBUTION_PENALTY = 0.01


def gold_markup_phrases():
    """Frases gold con su marca de itálica (emph)."""
    return gold_phrases(json.loads(GOLD.read_text(encoding="utf-8")))


def text_only_words(phrases):
    """Palabras de todas las frases sin marca de énfasis: el conjunto (a)."""
    return [{"text": w["text"], "start": w["start"], "end": w["end"]} for phrase in phrases for w in phrase]


def load_clip(name):
    """Palabras de Whisper de un clip y sus metadatos, desde tests/fixtures/ken_remedie/whisper."""
    data = json.loads((WHISPER / CLIPS[name]["file"]).read_text(encoding="utf-8"))
    return data["words"]


def window_phrases(phrases, offset, duration, tolerance=0.5):
    """Frases gold que caen dentro del clip, con tiempos en segundos de clip. Se descartan las que empiezan antes."""
    kept = []
    for phrase in phrases:
        start, end = phrase[0]["start"] - offset, phrase[-1]["end"] - offset
        if start < -0.05 or end > duration + tolerance:
            continue
        kept.append([{**w, "start": w["start"] - offset, "end": w["end"] - offset} for w in phrase])
    return kept


def norm(text):
    """Minúsculas, sin signos ni comillas. Los apóstrofos internos se conservan."""
    return re.sub(r"[^a-z0-9']", "", text.lower().replace("’", "'"))


def align(whisper, gold):
    """Tokens del gold que casan con una palabra de Whisper: {índice gold: índice whisper}."""
    a = [norm(w["text"]) for w in gold]
    b = [norm(w["text"]) for w in whisper]
    mapping = {}
    for block in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_matching_blocks():
        for offset in range(block.size):
            if a[block.a + offset]:
                mapping[block.a + offset] = block.b + offset
    return mapping


def gold_ends_of(phrases):
    """Índice (dentro de la lista plana de palabras) de la última palabra de cada frase, sin la última frase."""
    ends, position = [], -1
    for phrase in phrases[:-1]:
        position += len(phrase)
        ends.append(position)
    return ends


def clip_case(name):
    """Palabras de Whisper del clip, y para cada frontera gold, su índice en Whisper (o None si no casa)."""
    clip = CLIPS[name]
    whisper = load_clip(name)
    phrases = window_phrases(gold_markup_phrases(), clip["offset"], clip["duration"])
    gold = [w for phrase in phrases for w in phrase]
    mapping = align(whisper, gold)
    ends = {}
    for end in gold_ends_of(phrases):
        ends[end] = mapping.get(end)
    matched = set(mapping.values())
    gold_in_whisper = {value for value in ends.values() if value is not None}
    return {"words": whisper, "valid": matched, "gold_ends": gold_in_whisper,
            "unmatched_gold_ends": sum(1 for value in ends.values() if value is None),
            "gold_phrases": phrases}


def score(words, style, valid, gold_ends):
    """Métricas de la segmentación de words con style. valid None significa que todas las palabras cuentan."""
    segments = build_segments(words, style, 1080, 1920)
    last = len(words) - 1
    predicted = {max(word["index"] for line in segment["lines"] for word in line) for segment in segments}
    predicted.discard(last)
    considered = predicted if valid is None else predicted & valid
    gold = set(gold_ends)
    hits = len(considered & gold)
    precision = hits / len(considered) if considered else 0.0
    recall = hits / len(gold) if gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    sizes = Counter(min(sum(len(line) for line in segment["lines"]), 5) for segment in segments)
    shares = {k: 100.0 * sizes.get(k, 0) / len(segments) for k in REFERENCE_SHARES}
    durations = [segment["end"] - segment["start"] for segment in segments]
    return {
        "durations": durations,
        "f1": f1,
        "precision": precision,
        "recall": recall,
        "hits": hits,
        "predicted": len(considered),
        "gold": len(gold),
        "shares": shares,
        "penalty": distribution_penalty(shares),
        "median": statistics.median(durations),
        "segments": len(segments),
    }


def distribution_penalty(shares):
    """Puntos por encima de la tolerancia de 03, sumados por reparto."""
    return sum(max(0.0, abs(shares[k] - REFERENCE_SHARES[k]) - DISTRIBUTION_TOLERANCE) for k in REFERENCE_SHARES)


def evaluate(style):
    """Resultados de (a) y (b) con un estilo resuelto, y el objetivo: F1 medio menos penalización de reparto."""
    text_phrases = gold_markup_phrases()
    recon = text_only_words(text_phrases)
    recon_style = {**style, "emphasis": "none"}
    a = score(recon, recon_style, None, gold_ends_of(text_phrases))
    b_results = {}
    for name in CLIPS:
        case = clip_case(name)
        b_results[name] = score(case["words"], {**style, "emphasis": "none"}, case["valid"], case["gold_ends"])
    b = _combine(b_results.values())
    objective = (a["f1"] + b["f1"]) / 2 - DISTRIBUTION_PENALTY * (a["penalty"] + b["penalty"]) / 2
    return {"a": a, "b": b, "b_clips": b_results, "objective": objective}


def _combine(results):
    """Un solo resultado para los dos clips: métricas sobre el total de fronteras y de segmentos."""
    results = list(results)
    hits = sum(r["hits"] for r in results)
    predicted = sum(r["predicted"] for r in results)
    gold = sum(r["gold"] for r in results)
    precision = hits / predicted if predicted else 0.0
    recall = hits / gold if gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    segments = sum(r["segments"] for r in results)
    durations = [d for r in results for d in r["durations"]]
    shares = {k: sum(r["shares"][k] * r["segments"] for r in results) / segments for k in REFERENCE_SHARES}
    return {"f1": f1, "precision": precision, "recall": recall, "hits": hits, "predicted": predicted,
            "gold": gold, "shares": shares, "penalty": distribution_penalty(shares),
            "median": statistics.median(durations), "segments": segments, "durations": durations}
