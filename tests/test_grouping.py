import pytest

from engine.grouping import (
    emphasized_indices,
    ends_sentence,
    group_words,
    italic_flags,
    line_measure,
    usable_width,
    wrap_lines,
)
from engine.styles import resolve

PRESETS = ["ken_remedie", "ken_classic", "serif_glow", "bold_karaoke", "phrase_box", "bold_caps_pop", "wellness_soft", "minimal_mono"]
PARAGRAPH = (
    "Hoy te comparto tres formas sencillas de estiramiento suave para dormir mejor. "
    "Respiración profunda, sin pantallas, y conscientemente cada noche."
)


def make_words(*items):
    return [{"text": text, "start": start, "end": end} for text, start, end in items]


def timed(text, step=0.3):
    """Palabras de un texto, una cada step segundos y con un hueco corto entre ellas."""
    return [
        {"text": token, "start": round(i * step, 3), "end": round(i * step + 0.9 * step, 3)}
        for i, token in enumerate(text.split())
    ]


def texts(group):
    return [word["text"] for word in group["words"]]


def line_width(group, line, style, width=1080, height=1920):
    measure, _ = line_measure(style, width, height)
    return measure([(group["words"][i]["text"], group["italic"][i]) for i in line])


def by_chars(items):
    return len(" ".join(text for text, _ in items))


def test_cuts_at_max_words_per_line():
    style = resolve("bold_karaoke", {"max_words_per_line": 3, "max_lines": 2})
    groups = group_words(timed("uno dos tres cuatro cinco"), style, 1080, 1920)
    assert [len(group["words"]) for group in groups] == [3, 2]


def test_cuts_on_silence_longer_than_0_6_seconds():
    words = make_words(("a", 0.0, 0.5), ("b", 1.2, 1.5), ("c", 1.5, 1.8))  # silencio de 0.7 s
    style = resolve("bold_karaoke", {"max_words_per_line": 10})
    assert [texts(g) for g in group_words(words, style, 1080, 1920)] == [["a"], ["b", "c"]]


def test_silence_of_0_55_seconds_does_not_cut():
    words = make_words(("a", 0.0, 0.5), ("b", 1.05, 1.5))  # silencio de 0.55 s
    style = resolve("bold_karaoke", {"max_words_per_line": 10})
    assert len(group_words(words, style, 1080, 1920)) == 1


def test_cuts_after_sentence_end_punctuation():
    words = make_words(
        ("Hola.", 0.0, 0.3), ("hoy", 0.3, 0.5), ("¿Qué?", 0.5, 0.9),
        ("y", 0.9, 1.0), ('"mejor!"', 1.0, 1.4), ("ok", 1.4, 1.6),
    )
    style = resolve("bold_karaoke", {"max_words_per_line": 10})
    assert [texts(g) for g in group_words(words, style, 1080, 1920)] == [
        ["Hola."], ["hoy", "¿Qué?"], ["y", '"mejor!"'], ["ok"],
    ]


def test_cuts_when_the_phrase_would_need_more_lines_than_allowed():
    words = make_words(("Dormir", 0, 0.3), ("mejor", 0.3, 0.6), ("cada", 0.6, 0.9), ("noche", 0.9, 1.2))
    one_line = resolve("bold_karaoke", {"max_words_per_line": 10, "max_lines": 1})
    two_lines = resolve("bold_karaoke", {"max_words_per_line": 10, "max_lines": 2})
    assert [texts(g) for g in group_words(words, one_line, 1080, 1920, max_chars=22)] == [
        ["Dormir", "mejor", "cada"], ["noche"],
    ]
    assert [texts(g) for g in group_words(words, two_lines, 1080, 1920, max_chars=22)] == [
        ["Dormir", "mejor", "cada", "noche"],
    ]


def test_group_keeps_start_end_and_line_indices():
    words = make_words(("Estiramientos", 0, 0.5), ("antes", 0.5, 0.8), ("dormir", 0.8, 1.2))
    (group,) = group_words(words, resolve("bold_karaoke"), 1080, 1920, max_chars=22)
    assert (group["start"], group["end"]) == (0, 1.2)
    assert group["lines"] == [[0, 1], [2]]


def test_wide_words_split_by_pixels_when_the_video_is_narrow():
    words = make_words(("conscientemente", 0, 0.3), ("respiración", 0.3, 0.6))
    (narrow,) = group_words(words, resolve("bold_karaoke"), 1080, 1920)
    (wide,) = group_words(words, resolve("bold_karaoke"), 2000, 1920)
    assert narrow["lines"] == [[0], [1]]
    assert wide["lines"] == [[0, 1]]


def test_usable_width_subtracts_scaled_margins_and_outline():
    assert usable_width(resolve("bold_karaoke"), 1080, 1920) == 904
    assert usable_width(resolve("bold_karaoke"), 720, 1280) == pytest.approx(904 * 2 / 3)


def test_bold_karaoke_lines_never_exceed_the_usable_width_at_1080():
    style = resolve("bold_karaoke")
    limit = usable_width(style, 1080, 1920)
    for group in group_words(timed(PARAGRAPH), style, 1080, 1920):
        for line in group["lines"]:
            assert line_width(group, line, style) <= limit


@pytest.mark.parametrize("preset", PRESETS)
def test_every_preset_keeps_lines_within_width_and_max_lines(preset):
    style = resolve(preset)
    limit = usable_width(style, 1080, 1920)
    groups = group_words(timed(PARAGRAPH), style, 1080, 1920)
    assert groups
    for group in groups:
        assert len(group["lines"]) <= style["max_lines"]
        for line in group["lines"]:
            if style["max_chars"] is not None:  # con max_chars el corte mide caracteres, no píxeles
                assert len(line) == 1 or len(" ".join(group["words"][i]["text"] for i in line)) <= style["max_chars"]
            else:
                assert len(line) == 1 or line_width(group, line, style) <= limit


def test_missing_font_still_wraps_using_the_fallback_width():
    style = resolve("bold_karaoke", {"font_family": "Fuente que no existe"})
    limit = usable_width(style, 1080, 1920)
    for group in group_words(timed(PARAGRAPH), style, 1080, 1920):
        for line in group["lines"]:
            assert len(line) == 1 or line_width(group, line, style) <= limit


def test_max_chars_override_counts_characters():
    style = resolve("bold_karaoke", {"max_words_per_line": 10, "max_lines": 1})
    groups = group_words(make_words(("Dormir", 0, 0.3), ("mejor", 0.3, 0.6)), style, 1080, 1920, max_chars=10)
    assert [texts(g) for g in groups] == [["Dormir"], ["mejor"]]


def test_wrap_lines_is_greedy_and_never_splits_a_word():
    items = [(word, False) for word in ["Dormir", "mejor", "es", "posible"]]
    assert wrap_lines(items, by_chars, 10) == [[0], [1, 2], [3]]
    assert wrap_lines([("Supercalifragilístico", False)], by_chars, 10) == [[0]]


def test_ends_sentence_ignores_closing_quotes_and_parentheses():
    assert ends_sentence('"fin."')
    assert ends_sentence("listo!)")
    assert not ends_sentence("hola,")


def test_auto_emphasis_picks_the_longest_non_stopword():
    members = [{"text": "Hola"}, {"text": "hoy"}, {"text": "comparto"}]
    assert emphasized_indices(members, resolve("ken_classic")) == {2}


def test_auto_emphasis_skips_stopwords_and_keeps_the_first_on_ties():
    members = [{"text": "de"}, {"text": "formas"}, {"text": "dormir"}]
    assert emphasized_indices(members, resolve("ken_classic")) == {1}


def test_single_word_group_gets_no_automatic_emphasis():
    assert emphasized_indices([{"text": "dormir"}], resolve("ken_classic")) == set()


def test_word_flags_take_priority_over_the_automatic_choice():
    members = [{"text": "dormir", "emph": True}, {"text": "mejor"}, {"text": "cada"}]
    assert emphasized_indices(members, resolve("ken_classic")) == {0}


def test_false_flag_excludes_a_word_from_the_automatic_choice():
    members = [{"text": "dormir", "emph": False}, {"text": "mejor"}]
    assert emphasized_indices(members, resolve("ken_classic")) == {1}


def test_emphasis_none_marks_nothing_even_when_flagged():
    assert emphasized_indices([{"text": "dormir", "emph": True}], resolve("bold_karaoke")) == set()


def test_karaoke_with_italic_measures_every_word_in_italic():
    assert italic_flags([{"text": "a"}, {"text": "b"}], set(), resolve("serif_glow")) == [True, True]


def test_groups_carry_emphasis_and_italic_flags():
    words = make_words(("Hola", 0, 0.5), ("hoy", 0.5, 1.0), ("comparto", 1.0, 1.6))
    (group,) = group_words(words, resolve("ken_classic"), 1080, 1920)
    assert group["emph"] == {2}
    assert group["italic"] == [False, False, True]
