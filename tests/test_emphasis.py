import json

import pytest

from engine.emphasis import Unit, best_unit, load_lexicon, normalize, select_emphasis, units
from engine.layout import build_segments
from engine.styles import resolve


def words(*items):
    return [{"text": text, "start": start, "end": end} for text, start, end in items]


def emphasized(segments):
    return [[word["text"] for line in segment["lines"] for word in line if word["emph"]] for segment in segments]


def test_lexicon_has_both_languages_and_two_word_compounds():
    lexicon = load_lexicon()
    assert lexicon.words["gut"] == (3, "cuerpo")
    assert lexicon.words["intestino"] == (3, "cuerpo")
    assert lexicon.words["enlace"] == (3, "cta")
    assert lexicon.compounds["chia seed"] == (3, "ingrediente")
    assert lexicon.compounds["social media"] == (3, "cta")
    assert lexicon.compounds["redes sociales"] == (3, "cta")
    assert all(len(key.split()) == 2 for key in lexicon.compounds)
    assert lexicon.quote_weight == 3
    assert lexicon.digits_weight == 1


def test_normalize_drops_case_accents_and_edge_punctuation_but_keeps_hyphens():
    assert normalize('"TEA"') == "tea"
    assert normalize("Estómago,") == "estomago"
    assert normalize("DMs.") == "dms"
    assert normalize("backed-up") == "backed-up"


def test_single_words_score_by_their_category():
    assert best_unit(["Your", "jeans", "dig"]) == Unit(2, 1, 2)  # objeto
    assert best_unit(["your", "metabolism,"]) == Unit(3, 1, 2)  # síntoma
    assert best_unit(["juice", "from", "a", "fresh"]) == Unit(2, 3, 4)  # adjetivo


def test_stopwords_and_contractions_are_never_units():
    assert units(["that's", "a", "the", "of"]) == []
    assert [unit.start for unit in units(["you're", "following"])] == [1]


def test_quoted_keyword_scores_as_a_call_to_action():
    assert best_unit(['"TEA"', "and", "I'll"]) == Unit(3, 0, 1)


def test_numbers_score_as_quantity():
    assert best_unit(["for", "20", "minutes"]) == Unit(1, 1, 2)


def test_a_compound_beats_a_single_word_only_when_it_scores_higher():
    assert best_unit(["the", "social", "media"]) == Unit(3, 1, 3)
    assert best_unit(["chia", "seed,"]) == Unit(3, 0, 1)  # empate: gana la palabra suelta


def test_select_emphasis_marks_the_best_phrases_up_to_the_ratio():
    phrases = [["the", "gut"], ["years"], ["fresh", "lemon"], ["nothing"]]
    assert select_emphasis(phrases, ratio=0.5) == [(1, 2), None, (1, 2), None]


def test_select_emphasis_without_ratio_marks_every_phrase_that_scores():
    phrases = [["gut"], ["years"], [], ["lemon"]]
    assert select_emphasis(phrases) == [(0, 1), (0, 1), None, (0, 1)]


def test_manual_phrases_count_toward_the_ratio_and_are_not_touched():
    phrases = [["gut"], ["lemon"], ["socks"], ["years"]]
    assert select_emphasis(phrases, ratio=0.5, marked=[0]) == [None, (0, 1), None, None]


def test_lexicon_marks_one_unit_per_phrase_and_keeps_the_punctuation_inside_the_word():
    style = resolve("ken_remedie", {"emphasis_ratio": None})
    segments = build_segments(words(("If", 0, 0.3), ("your", 0.3, 0.6), ("socks", 0.6, 1.0),
                                    ("leave,", 1.0, 1.3)), style, 1080, 1920)
    assert emphasized(segments) == [["socks"]]


def test_lexicon_respects_the_ratio_over_the_whole_text():
    sample = words(("gut.", 0, 0.3), ("years.", 0.4, 0.7), ("lemon.", 0.8, 1.1), ("nothing.", 1.2, 1.5))
    style = resolve("ken_remedie", {"emphasis_ratio": 0.5, "max_chars": 100})
    marked = emphasized(build_segments(sample, style, 1080, 1920))
    assert sum(1 for phrase in marked if phrase) == 2
    assert marked[0] == ["gut."] and marked[2] == ["lemon."]  # las de mayor puntaje


def test_manual_emphasis_wins_over_the_lexicon_in_its_phrase():
    sample = words(("If", 0, 0.3), ("your", 0.3, 0.6), ("socks", 0.6, 1.0, ), ("leave", 1.0, 1.3))
    sample[1]["emph"] = True
    style = resolve("ken_remedie", {"max_chars": 100})
    assert emphasized(build_segments(sample, style, 1080, 1920)) == [["your"]]


def test_turning_the_lexicon_off_keeps_only_manual_marks():
    sample = words(("If", 0, 0.3), ("your", 0.3, 0.6), ("socks", 0.6, 1.0))
    assert emphasized(build_segments(sample, resolve("ken_remedie", {"emphasis_auto": False}), 1080, 1920)) == [[]]
    assert emphasized(build_segments(sample, resolve("ken_remedie", {"emphasis": "none"}), 1080, 1920)) == [[]]


def test_length_engine_keeps_the_previous_choice():
    sample = words(("Hola", 0, 0.3), ("comparto", 0.3, 0.9))
    style = resolve("ken_remedie", {"emphasis_engine": "length", "max_chars": 100, "max_words_per_line": 4})
    assert emphasized(build_segments(sample, style, 1080, 1920)) == [["comparto"]]


def test_compound_units_mark_both_words():
    sample = words(("the", 0, 0.3), ("social", 0.3, 0.6), ("media", 0.6, 0.9))
    style = resolve("ken_remedie", {"max_chars": 100, "emphasis_ratio": None})  # con 1 frase, ratio 0.3 marca 0
    assert emphasized(build_segments(sample, style, 1080, 1920)) == [["social", "media"]]


def test_ratio_of_one_phrase_marks_none_when_rounded_down():
    sample = words(("the", 0, 0.3), ("social", 0.3, 0.6), ("media", 0.6, 0.9))
    assert emphasized(build_segments(sample, resolve("ken_remedie", {"max_chars": 100}), 1080, 1920)) == [[]]


def test_an_added_word_takes_effect_after_editing_the_lexicon(tmp_path):
    path = tmp_path / "lexicon.json"
    path.write_text(json.dumps({"peso_comillas": 1, "categorias": {
        "marca": {"peso": 5, "palabras": {"en": ["acme"], "es": []}, "compuestos": {"en": [], "es": []}},
    }}), encoding="utf-8")
    lexicon = load_lexicon(path)
    assert best_unit(["the", "acme"], lexicon) == Unit(5, 1, 2)


@pytest.mark.parametrize("body, message", [
    ({"peso": 0, "palabras": {"en": ["x"]}}, "entero de 1 a 10"),
    ({"peso": 2, "compuestos": {"en": ["a b c"]}}, "debe tener 2 palabras"),
    ({"peso": 2, "compuestos": {"en": ["the gut"]}}, "tiene una stopword"),
    ({"peso": 2, "palabras": {"en": ["two words"]}}, "debe ser una sola palabra"),
])
def test_an_invalid_lexicon_entry_is_reported(tmp_path, body, message):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"categorias": {"mala": body}}), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_lexicon(path)
