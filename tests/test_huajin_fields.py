import warnings

import pytest

from engine.emphasis import select_emphasis_multi
from engine.grouping import balanced_lines, group_words, wrap_lines
from engine.styles import display_text, resolve, shown_texts
from engine.textmetrics import font_catalog, text_width


def words(*items):
    return [{"text": text, "start": start, "end": end} for text, start, end in items]


def test_font_size_accepts_decimals_because_it_is_the_libass_fontsize():
    assert resolve("huajin_editorial")["font_size"] == 111.56  # 78 px CSS / css_scale de Inter SemiBold


def test_the_three_hua_jin_presets_resolve_without_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for name in ("huajin_editorial", "huajin_karaoke_azul", "huajin_basico"):
            assert resolve(name)["mode"] in ("reveal", "karaoke_box", "phrase")


@pytest.mark.parametrize("overrides", [
    {"text_case": "title"},
    {"x_pct": 1.5},
    {"text_align": "right"},
    {"line_height": 0.2},
    {"reveal_fade_ms": -1},
    {"highlight_box_radius": -2},
    {"emphasis_font_family": ""},
    {"emphasis_size_scale": 0},
    {"emphasis_max_per_segment": 0},
    {"emphasis_letter_spacing": 99},
    {"split_before_words": ["two words"]},
    {"split_before_words": "and"},
    {"exact_metrics": "yes"},
    {"balance_lines": 1},
    {"mode": "scroll"},
])
def test_invalid_values_of_the_new_fields_raise(overrides):
    with pytest.raises(ValueError):
        resolve("ken_remedie", overrides)


def test_valid_values_of_the_new_fields_are_accepted():
    style = resolve("ken_remedie", {
        "text_case": "lower_smart", "x_pct": 0.08, "text_align": "left", "line_height": 1.05,
        "reveal_fade_ms": 0, "highlight_box_radius": 7, "emphasis_font_family": "Instrument Serif",
        "emphasis_size_scale": 1.6, "emphasis_letter_spacing": None, "emphasis_max_per_segment": 2,
        "split_before_words": ["and", "y"], "balance_lines": True, "exact_metrics": True,
    })
    assert style["text_case"] == "lower_smart" and style["split_before_words"] == ["and", "y"]


def test_uppercase_alias_and_text_case_upper_give_the_same_text():
    assert display_text("hello", resolve("ken_remedie", {"text_case": "upper"})) == "HELLO"
    assert display_text("hello", resolve("ken_remedie", {"uppercase": True})) == "HELLO"


def test_lower_smart_keeps_i_acronyms_and_mid_sentence_names_and_lowers_the_rest():
    style = resolve("huajin_basico")
    sample = words(("When", 0, .2), ("I", .2, .3), ("saw", .3, .5), ("Marvella", .5, .9), ("Amla", .9, 1.2),
                   ("PM", 1.2, 1.4), ("vitamin", 1.4, 1.7), ("C.", 1.7, 1.9), ("Then", 2.0, 2.2), ("I'm", 2.2, 2.4))
    assert shown_texts(sample, style) == ["when", "I", "saw", "Marvella", "Amla", "PM", "vitamin", "C", "then", "I'm"]


def test_strip_punctuation_keeps_the_apostrophe_inside_a_word():
    style = resolve("huajin_basico")
    assert shown_texts(words(("\"Don't,\"", 0, .2), ("3.5", .2, .4), ("it's", .4, .6)), style) == ["don't", "35", "it's"]


def test_split_before_connectors_needs_the_minimum_words_first():
    style = resolve("huajin_basico", {"max_chars": 100, "max_words_per_line": 10, "pause_split_min_words": 4,
                                      "pause_split_s": 5, "merge_orphans": False, "max_lines": 3})
    sample = words(("one", 0, .2), ("two", .2, .4), ("three", .4, .6), ("four", .6, .8),
                   ("and", .8, 1.0), ("five", 1.0, 1.2), ("six", 1.2, 1.4), ("seven", 1.4, 1.6))
    groups = group_words(sample, style, 1080, 1920)
    assert [[word["text"] for word in group["words"]] for group in groups] == [
        ["one", "two", "three", "four"], ["and", "five", "six", "seven"]]


def test_connector_before_the_minimum_word_count_does_not_cut():
    style = resolve("huajin_basico", {"max_chars": 100, "max_words_per_line": 10, "pause_split_min_words": 4,
                                      "pause_split_s": 5, "merge_orphans": False, "max_lines": 3})
    sample = words(("one", 0, .2), ("and", .2, .4), ("two", .4, .6))
    assert len(group_words(sample, style, 1080, 1920)) == 1


def test_emphasis_max_per_segment_allows_two_lexicon_words_in_one_block():
    phrase = [["Drink", "this", "every", "morning", "on", "an", "empty", "stomach"]]
    one = select_emphasis_multi(phrase, ratio=None, max_words=None)
    two = select_emphasis_multi(phrase, ratio=None, max_words=2)
    assert len(one[0]) == 1
    assert len(two[0]) == 2
    assert sum(end - start for start, end in two[0]) <= 2


def test_balance_lines_splits_a_two_line_page_into_halves_and_keeps_one_line_pages():
    items = [("ESPECIALLY", False), ("AROUND", False), ("YOUR", False), ("MIDSECTION", False)]

    def measure(sample):
        return len(" ".join(text for text, _ in sample))

    assert wrap_lines(items, measure, 30) == [[0, 1, 2], [3]]
    assert balanced_lines(items, measure, 30) == [[0, 1], [2, 3]]
    assert balanced_lines(items[:2], measure, 30) == [[0, 1]]


def test_kerning_changes_the_measured_width_of_kerned_pairs():
    # Inter SemiBold trae la característica kern en GPOS. Poppins ExtraBold no la tiene, así que kerning no cambia nada.
    plain = text_width("AVATAR To", "Inter SemiBold", False, 100)
    kerned = text_width("AVATAR To", "Inter SemiBold", False, 100, kerning=True)
    assert kerned < plain
    assert text_width("AVATAR To", "Poppins ExtraBold", False, 100, kerning=True) == text_width(
        "AVATAR To", "Poppins ExtraBold", False, 100)


def test_the_new_static_fonts_are_in_the_catalog_under_their_internal_family_names():
    entries = {entry["family"]: entry for entry in font_catalog()}
    for family in ("Inter SemiBold", "Montserrat Medium", "Poppins ExtraBold"):
        assert family in entries
        assert entries[family]["bold"] is False and entries[family]["italic"] is False
        assert "[" not in entries[family]["file"]
    assert entries["Inter SemiBold"]["css_scale"] == pytest.approx(2048 / (2269 + 660))
