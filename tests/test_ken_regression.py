"""Regresión contra el timeline gold de ken_remedie: segmentación en (a) y (b), y énfasis por léxico.

(a) es el gold reconstruido, sin pausas: mide las reglas de texto. (b) son los dos clips con palabras de Whisper
guardadas en tests/fixtures/ken_remedie/whisper, así que el test no ejecuta Whisper. Los umbrales son lo medido hoy
menos un margen de 5 puntos. Si un cambio los rompe, hay que revisar la regresión; bajar un umbral solo tiene
sentido después de volver a medir.
"""

import json
from pathlib import Path

import ken_eval
from engine.emphasis import select_emphasis
from engine.styles import resolve

# Medido con el preset actual, Whisper small y el gold corregido (GOLD_FIXES.md, corrección 1):
# (a) F1 51,6 % | (b) F1 60,0 % (clip19 63,2 %, clip84 57,1 %). Umbrales: medido menos 5 puntos.
F1_TEXT_MIN = 0.46
F1_AUDIO_MIN = 0.55
# Objetivo de la mediana de duración de frase, en segundos. Medido: (a) 0,75 y (b) 0,72.
MEDIAN_RANGE = (0.70, 0.90)
# Medido: 29,6 % de frases con itálica al ratio 0,30. El rango es el de docs/03 (25 a 40 %).
ITALIC_SHARE_RANGE = (0.25, 0.40)
# Medido sobre las 108 frases gold: precisión 85,3 % y recall 82,9 %.
EMPHASIS_MIN = 0.80


def _style():
    return resolve("ken_remedie", {"emphasis": "none"})


def test_text_only_boundaries_f1_is_above_the_floor():
    phrases = ken_eval.gold_markup_phrases()
    words = ken_eval.text_only_words(phrases)
    result = ken_eval.score(words, _style(), None, ken_eval.gold_ends_of(phrases))
    assert result["f1"] >= F1_TEXT_MIN
    assert MEDIAN_RANGE[0] <= result["median"] <= MEDIAN_RANGE[1]


def test_audio_boundaries_f1_is_above_the_floor_on_the_fixed_whisper_words():
    results = []
    for name in ken_eval.CLIPS:
        case = ken_eval.clip_case(name)
        assert case["unmatched_gold_ends"] == 0, name  # el fixture debe casar con todas las fronteras gold
        results.append(ken_eval.score(case["words"], _style(), case["valid"], case["gold_ends"]))
    combined = ken_eval._combine(results)
    assert combined["f1"] >= F1_AUDIO_MIN
    assert MEDIAN_RANGE[0] <= combined["median"] <= MEDIAN_RANGE[1]


def test_whisper_fixtures_record_the_model_and_the_clip_window():
    for name, meta in ken_eval.CLIPS.items():
        data = json.loads((ken_eval.WHISPER / meta["file"]).read_text(encoding="utf-8"))
        assert data["model"] == "small" and data["language"] == "en"
        assert data["offset"] == meta["offset"] and data["duration"] == meta["duration"]
        assert data["words"], name


def test_italic_share_of_the_gold_phrases_is_in_the_range():
    phrases = ken_eval.gold_markup_phrases()
    chosen = select_emphasis([[word["text"] for word in phrase] for phrase in phrases], ratio=0.30)
    share = sum(1 for unit in chosen if unit) / len(phrases)
    assert ITALIC_SHARE_RANGE[0] <= share <= ITALIC_SHARE_RANGE[1]


def test_lexicon_words_match_the_gold_italics():
    phrases = ken_eval.gold_markup_phrases()
    texts = [[word["text"] for word in phrase] for phrase in phrases]
    gold_italic = {(p, i) for p, phrase in enumerate(phrases) for i, word in enumerate(phrase) if word["emph"]}
    chosen = select_emphasis(texts, ratio=0.30)
    predicted = {(p, i) for p, unit in enumerate(chosen) if unit for i in range(*unit)}
    hits = len(predicted & gold_italic)
    assert hits / len(predicted) >= EMPHASIS_MIN
    assert hits / len(gold_italic) >= EMPHASIS_MIN


def test_gold_fix_1_keeps_straight_to_your_between_protocols_and_dms():
    data = json.loads(ken_eval.GOLD.read_text(encoding="utf-8"))
    phrases = [segment for segment in data["segments"] if segment.get("markup")]
    index = next(i for i, segment in enumerate(phrases) if segment["markup"] == "*health protocols*")
    assert phrases[index]["end"] == 87.533
    assert (phrases[index + 1]["markup"], phrases[index + 1]["start"], phrases[index + 1]["end"]) == (
        "straight to your", 87.6, 88.1)
    assert phrases[index + 2]["markup"] == "*DMs.*" and phrases[index + 2]["start"] == 88.1
    srt = ken_eval.GOLD.with_suffix(".srt").read_text(encoding="utf-8")
    assert "00:01:27,600 --> 00:01:28,100\nstraight to your" in srt
