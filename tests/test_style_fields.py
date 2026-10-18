import pytest

from engine.ass_builder import build_ass
from engine.grouping import group_words
from engine.layout import build_segments
from engine.styles import resolve


def words(*items):
    return [{"text": text, "start": start, "end": end} for text, start, end in items]


def texts(groups):
    return [[word["text"] for word in group["words"]] for group in groups]


def style_fields(ass):
    line = next(line for line in ass.splitlines() if line.startswith("Style: "))
    return line[len("Style: "):].split(",")


def dialogue_texts(ass):
    return [line.split(",", 9)[9] for line in ass.splitlines() if line.startswith("Dialogue: ")]


KEN_WORDS = words(
    ("If", 0.0, 0.3), ("your", 0.3, 0.6), ("socks", 0.6, 1.0), ("leave", 1.0, 1.3),
    ("marks", 1.3, 1.6), ("like", 1.6, 1.9), ("this,", 1.9, 2.2),
)


def test_ken_style_line_at_1080_matches_the_reference_style():
    fields = style_fields(build_ass(KEN_WORDS, resolve("ken_remedie"), 1080, 1920))
    assert fields[1] == "Playfair Display"
    assert fields[2] == "132"
    assert fields[5] == "&H70000000"  # OutlineColour: negro con alfa 0x70, el halo
    assert fields[6] == "&HFF000000"  # BackColour transparente
    assert fields[7] == "0"  # sin negrita
    assert fields[11] == "76" and fields[12] == "100"  # ScaleX de scale_x, ScaleY fijo
    assert fields[15] == "1"  # BorderStyle normal
    assert fields[16] == "3"  # Outline = outline_width
    assert fields[17] == "0"  # Shadow 0: el halo no se desplaza
    assert fields[18] == "5"  # alineación central, porque hay y_pct
    assert fields[21] == "0"  # MarginV no aplica con \pos


def test_halo_event_starts_with_pos_blur_and_letter_spacing_like_the_reference():
    line = next(line for line in build_ass(KEN_WORDS, resolve("ken_remedie"), 1080, 1920).splitlines()
                if line.startswith("Dialogue: "))
    assert ",,{\\pos(540,1066)\\blur6\\fsp-5.25}" in line


def test_ken_at_720x1280_scales_size_outline_blur_spacing_and_position():
    ass = build_ass(KEN_WORDS, resolve("ken_remedie", {"y_pct": 0.554}), 720, 1280)
    fields = style_fields(ass)
    assert fields[2] == "88"
    assert fields[16] == "2"
    line = next(line for line in ass.splitlines() if line.startswith("Dialogue: "))
    assert "\\pos(360,709)\\blur4\\fsp-3.5" in line


def test_italic_run_carries_its_own_scale_and_restores_the_regular_one():
    emphasized = [dict(word, emph=True) if word["text"] == "socks" else word for word in KEN_WORDS]
    text = dialogue_texts(build_ass(emphasized, resolve("ken_remedie"), 1080, 1920))[0]
    assert "{\\i1\\fscx82}socks{\\i0\\fscx76}" in text


def test_word_spaces_are_compressed_and_restored_to_scale_x():
    text = dialogue_texts(build_ass(KEN_WORDS, resolve("ken_remedie"), 1080, 1920))[0]
    assert "If{\\fscx45} {\\fscx76}your" in text


def test_italic_scale_null_means_the_same_scale_as_the_regular_text():
    style = resolve("ken_remedie", {"scale_x_italic": None})
    emphasized = [dict(word, emph=True) if word["text"] == "socks" else word for word in KEN_WORDS]
    text = dialogue_texts(build_ass(emphasized, style, 1080, 1920))[0]
    assert "{\\i1}socks{\\i0}" in text


def test_default_styles_add_no_scale_spacing_or_position_tags():
    text = dialogue_texts(build_ass(KEN_WORDS, resolve("minimal_mono"), 1080, 1920))[0]
    assert "\\fscx" not in text and "\\fsp" not in text and "\\pos" not in text and "\\blur" not in text


def test_letter_spacing_zero_adds_no_fsp_tag():
    text = dialogue_texts(build_ass(KEN_WORDS, resolve("ken_remedie", {"letter_spacing": 0}), 1080, 1920))[0]
    assert "\\fsp" not in text


def test_y_pct_positions_every_event_and_ignores_alignment_and_margin():
    style = resolve("ken_remedie", {"y_pct": 0.3, "alignment": 1, "margin_v": 100})
    ass = build_ass(KEN_WORDS, style, 1080, 1920)
    fields = style_fields(ass)
    assert fields[18] == "5" and fields[21] == "0"
    lines = [line for line in ass.splitlines() if line.startswith("Dialogue: ")]
    assert lines and all("\\pos(540,576)" in line for line in lines)


def test_halo_outline_colour_follows_shadow_colour_and_opacity():
    fields = style_fields(build_ass(KEN_WORDS, resolve("ken_remedie", {"shadow_color": "#FFFFFF"}), 1080, 1920))
    assert fields[5] == "&H70FFFFFF"
    fields = style_fields(build_ass(KEN_WORDS, resolve("ken_remedie", {"shadow_opacity": 1.0}), 1080, 1920))
    assert fields[5] == "&H00000000"


def test_halo_blur_follows_shadow_blur():
    text = dialogue_texts(build_ass(KEN_WORDS, resolve("ken_remedie", {"shadow_blur": 10}), 1080, 1920))[0]
    assert "\\blur10" in text


def test_halo_is_one_layer_without_soft_copy():
    ass = build_ass(KEN_WORDS, resolve("ken_remedie"), 1080, 1920)
    layers = {line.split(",")[0] for line in ass.splitlines() if line.startswith("Dialogue: ")}
    assert layers == {"Dialogue: 0"}


@pytest.mark.parametrize("overrides", [
    {"y_pct": 1.5},
    {"y_pct": "0.5"},
    {"scale_x": 0},
    {"scale_x_italic": "82"},
    {"letter_spacing": 100},
    {"word_space_scale": 0},
    {"punctuation_closes": "a"},
    {"punctuation_closes": ",,x"},
    {"max_chars": 0},
    {"max_chars": 2.5},
    {"pause_split_min_words": 0},
    {"merge_orphans": "yes"},
    {"blank_gap_s": -1},
    {"tail_s": -0.1},
    {"min_duration_s": 9},
    {"pause_split_s": -0.2},
    {"emphasis_engine": "magic"},
    {"emphasis_ratio": 2},
    {"shadow_style": "glow"},
])
def test_invalid_new_field_values_raise(overrides):
    with pytest.raises(ValueError):
        resolve("ken_remedie", overrides)


def test_valid_new_field_values_are_accepted():
    style = resolve("ken_remedie", {
        "scale_x": 100, "scale_x_italic": None, "letter_spacing": -5.25, "word_space_scale": 45,
        "y_pct": None, "max_chars": 24, "punctuation_closes": "", "pause_split_min_words": 2,
        "merge_orphans": True, "blank_gap_s": None, "emphasis_ratio": None,
    })
    assert style["punctuation_closes"] == ""


def test_max_chars_cuts_by_characters_not_pixels():
    style = resolve("ken_remedie", {"max_chars": 10, "max_words_per_line": 10, "pause_split_s": 5, "merge_orphans": False})
    groups = group_words(words(("Dormir", 0, 0.3), ("mejor", 0.3, 0.6), ("cada", 0.6, 0.9)), style, 1080, 1920)
    assert texts(groups) == [["Dormir"], ["mejor", "cada"]]  # "Dormir mejor" tiene 12 caracteres; "mejor cada" tiene 10


def test_punctuation_closes_decides_which_marks_end_a_phrase():
    sample = words(("uno,", 0, 0.3), ("dos", 0.3, 0.6))
    default = resolve("ken_remedie", {"max_chars": 100, "punctuation_closes": ".?!"})
    commas = resolve("ken_remedie", {"max_chars": 100, "punctuation_closes": ",.?!:;"})
    assert texts(group_words(sample, default, 1080, 1920)) == [["uno,", "dos"]]
    assert texts(group_words(sample, commas, 1080, 1920)) == [["uno,"], ["dos"]]


def test_pause_split_needs_the_minimum_number_of_words_before_it_cuts():
    sample = words(("uno", 0, 0.2), ("dos", 0.2, 0.4), ("tres", 0.8, 1.0))  # pausa de 0.4 s tras "dos"
    two = resolve("ken_remedie", {"max_chars": 100, "pause_split_min_words": 2})
    three = resolve("ken_remedie", {"max_chars": 100, "pause_split_min_words": 3})
    assert texts(group_words(sample, two, 1080, 1920)) == [["uno", "dos"], ["tres"]]
    assert texts(group_words(sample, three, 1080, 1920)) == [["uno", "dos", "tres"]]


def test_pause_after_one_word_does_not_cut_when_two_words_are_required():
    sample = words(("uno", 0, 0.2), ("dos", 0.6, 0.8))  # pausa de 0.4 s tras la primera palabra
    style = resolve("ken_remedie", {"max_chars": 100, "pause_split_min_words": 2})
    assert texts(group_words(sample, style, 1080, 1920)) == [["uno", "dos"]]


def test_merge_orphans_joins_a_short_gap_and_keeps_a_long_one_apart():
    short_gap = words(("Dormir", 0, 0.3), ("mejor", 0.3, 0.6), ("cada", 0.6, 0.9), ("noche", 1.1, 1.4))
    long_gap = words(("Dormir", 0, 0.3), ("mejor", 0.3, 0.6), ("cada", 0.6, 0.9), ("noche", 1.5, 1.8))
    style = resolve("ken_remedie", {"max_chars": 100, "max_words_per_line": 4, "merge_orphans": False})
    merged = resolve("ken_remedie", {"max_chars": 100, "max_words_per_line": 4, "merge_orphans": True,
                                 "target_words": None, "soft_max_chars": None, "hang_max_chars": 0})
    assert len(group_words(short_gap, style, 1080, 1920)) == 2
    assert texts(group_words(short_gap, merged, 1080, 1920)) == [["Dormir", "mejor", "cada", "noche"]]
    assert texts(group_words(long_gap, merged, 1080, 1920)) == [["Dormir", "mejor", "cada"], ["noche"]]


def test_merge_orphans_never_joins_past_a_sentence_end():
    sample = words(("Dormir.", 0, 0.3), ("mejor", 0.4, 0.6))
    merged = resolve("ken_remedie", {"max_chars": 100, "merge_orphans": True})
    assert texts(group_words(sample, merged, 1080, 1920)) == [["Dormir."], ["mejor"]]


def test_merge_orphans_respects_the_word_limit():
    sample = words(("uno", 0, 0.2), ("dos", 0.2, 0.4), ("tres", 0.4, 0.6), ("cuatro", 0.6, 0.8), ("cinco", 0.9, 1.1))
    merged = resolve("ken_remedie", {"max_chars": 100, "max_words_per_line": 4, "merge_orphans": True,
                                 "target_words": None, "soft_max_chars": None, "hang_max_chars": 0})
    assert texts(group_words(sample, merged, 1080, 1920)) == [["uno", "dos", "tres", "cuatro"], ["cinco"]]


def test_blank_gap_below_the_threshold_runs_into_the_next_phrase():
    sample = words(("Hola", 0.0, 0.3), ("amigo.", 0.35, 0.5), ("mundo", 0.7, 1.0))  # hueco de 0.2 s < 0.3 s
    segments = build_segments(sample, resolve("ken_remedie"), 1080, 1920)
    assert [(s["start"], s["end"]) for s in segments] == [(0.0, 0.7), (0.7, pytest.approx(1.05))]


def test_blank_gap_at_or_above_the_threshold_ends_after_tail_s():
    sample = words(("Hola", 0.0, 0.3), ("amigo.", 0.35, 0.5), ("mundo", 1.0, 1.4))  # hueco de 0.5 s
    segments = build_segments(sample, resolve("ken_remedie"), 1080, 1920)
    assert segments[0]["end"] == pytest.approx(0.55)
    assert segments[1]["end"] == pytest.approx(1.45)


def test_min_duration_extends_short_phrases_but_never_past_the_next_phrase():
    alone = build_segments(words(("ok.", 0.0, 0.1), ("bien", 0.9, 1.2)), resolve("ken_remedie"), 1080, 1920)
    assert alone[0]["end"] == pytest.approx(0.3)
    tight = build_segments(words(("ok.", 0.0, 0.1), ("hola", 0.2, 0.4)), resolve("ken_remedie"), 1080, 1920)
    assert tight[0]["end"] == pytest.approx(0.2)


def test_min_duration_and_tail_do_nothing_without_blank_gap():
    style = resolve("ken_remedie", {"blank_gap_s": None, "tail_s": 0.5, "min_duration_s": 2})
    segments = build_segments(words(("Hola.", 0.0, 0.5), ("mundo", 1.0, 1.4)), style, 1080, 1920)
    assert segments[0]["end"] == pytest.approx(0.8)  # hold heredado: 0.3 s tras la última palabra
