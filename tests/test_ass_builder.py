import math

import pytest
from fontTools.ttLib import TTFont

from engine.ass_builder import ANIMATION_TAGS, PHRASE_POP, WORD_POP, ass_color, ass_time, build_ass, escape_text
from engine.grouping import usable_width
from engine.styles import resolve
from engine.textmetrics import FONTS_DIR

PRESETS = ["ken_remedie", "ken_classic", "serif_glow", "bold_karaoke", "phrase_box", "bold_caps_pop", "wellness_soft", "minimal_mono"]
SAMPLE = [
    ("Hoy", 0.0, 0.3), ("te", 0.3, 0.5), ("comparto", 0.5, 1.0), ("tres", 1.0, 1.3), ("formas.", 1.3, 1.8),
    ("Respira", 2.4, 2.9), ("despacio", 2.9, 3.5), ("y", 3.5, 3.6), ("suelta", 3.6, 4.1),
    ("los", 4.1, 4.2), ("hombros.", 4.2, 4.9), ("Después", 5.0, 5.5), ("duerme", 5.5, 6.0), ("mejor", 6.0, 6.5),
]
LONG_WORD = "supercalifragilisticoexpi"  # 25 caracteres


def make_words(*items):
    return [{"text": text, "start": start, "end": end} for text, start, end in items]


def dialogues(ass, layer=None):
    lines = [line for line in ass.splitlines() if line.startswith("Dialogue: ")]
    if layer is None:
        return lines
    return [line for line in lines if line.startswith(f"Dialogue: {layer},")]


def event_text(line):
    return line.split("Default,,0,0,0,,", 1)[1]


def times(line):
    parts = line.split(",")
    return parts[1], parts[2]


def centis(stamp):
    hours, minutes, rest = stamp.split(":")
    seconds, cs = rest.split(".")
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 100 + int(cs)


def style_fields(ass):
    line = next(line for line in ass.splitlines() if line.startswith("Style: "))
    return line[len("Style: "):].split(",")


def montserrat_bold_width(text, size):
    with TTFont(FONTS_DIR / "Montserrat-Bold.ttf") as font:
        cmap, hmtx, upem = font.getBestCmap(), font["hmtx"], font["head"].unitsPerEm
        return sum(hmtx[cmap[ord(char)]][0] for char in text) * size / upem


def scaled_pop(k):
    peak, base = f"{112 * k:g}", f"{100 * k:g}"
    phrase = f"\\t(0,110,\\fscx{peak}\\fscy{peak})\\t(110,220,\\fscx{base}\\fscy{base})"
    word = f"\\t(0,90,\\fscx{peak}\\fscy{peak})\\t(90,180,\\fscx{base}\\fscy{base})"
    return phrase, word


def test_hex_color_becomes_bgr_with_alpha():
    assert ass_color("#FFD400") == "&H0000D4FF"
    assert ass_color("#112233") == "&H00332211"
    assert ass_color("#1B3A33", alpha=0x66) == "&H66333A1B"


def test_escape_replaces_braces_and_backslash():
    assert escape_text("{a}\\N") == "｛a｝＼N"


def test_ass_time_uses_centiseconds():
    assert ass_time(3723.45) == "1:02:03.45"
    assert ass_time(0.004) == "0:00:00.00"


def test_play_res_matches_video_size():
    ass = build_ass(make_words(("Hola", 0, 0.5)), resolve("ken_classic"), 1080, 1920)
    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass


def test_karaoke_sweep_puts_highlight_in_primary_colour():
    fields = style_fields(build_ass(make_words(("Hola", 0, 0.5)), resolve("wellness_soft"), 1080, 1920))
    assert fields[3] == ass_color("#7FE0C1")
    assert fields[4] == ass_color("#FFF4E0")


def test_other_modes_keep_text_colour_in_primary():
    fields = style_fields(build_ass(make_words(("Hola", 0, 0.5)), resolve("ken_classic"), 1080, 1920))
    assert fields[3] == "&H00FFFFFF"
    assert fields[4] == "&H0000D4FF"


def test_box_uses_border_style_3_and_opacity_in_back_and_outline_colour():
    fields = style_fields(build_ass(make_words(("Hola", 0, 0.5)), resolve("phrase_box"), 1080, 1920))
    assert fields[15] == "3"
    assert fields[5] == "&H66000000"  # OutlineColour: la caja si libass la usa
    assert fields[6] == "&H66000000"  # BackColour: 60 % de opacidad


def test_without_box_uses_border_style_1_and_opaque_hard_shadow():
    fields = style_fields(build_ass(make_words(("Hola", 0, 0.5)), resolve("bold_karaoke"), 1080, 1920))
    assert fields[15] == "1"
    assert fields[6] == "&H00000000"  # shadow_opacity 1.0 mantiene la sombra opaca de antes


def test_bold_flag_is_minus_one_only_when_bold():
    assert style_fields(build_ass([], resolve("bold_karaoke"), 1080, 1920))[7] == "-1"
    assert style_fields(build_ass([], resolve("ken_classic"), 1080, 1920))[7] == "0"


def test_reference_units_scale_with_height_over_1920():
    style = resolve("bold_karaoke")
    fields = style_fields(build_ass(make_words(("Hola", 0, 0.5)), style, 720, 1280))
    assert fields[2] == "64"  # font_size 96 * 1280 / 1920
    assert fields[16] == "5.33"  # outline 8 escalado
    assert fields[19] == "53"  # margin_h 80 escalado
    assert fields[21] == "280"  # margin_v 420 escalado


def test_720x1280_keeps_the_layout_of_1080x1920():
    words = make_words(("Dormir", 0.0, 0.5), ("mejor", 0.5, 1.0), ("cada", 1.0, 1.4))
    style = resolve("bold_karaoke")
    big = build_ass(words, style, 1080, 1920)
    small = build_ass(words, style, 720, 1280)
    assert [event_text(line) for line in dialogues(big)] == [event_text(line) for line in dialogues(small)]
    assert [times(line) for line in dialogues(big)] == [times(line) for line in dialogues(small)]
    size_big, size_small = float(style_fields(big)[2]), float(style_fields(small)[2])
    assert size_small / 1280 == pytest.approx(size_big / 1920, rel=1e-3)


def test_phrase_mode_emits_one_dialogue_per_phrase_held_until_the_next_phrase():
    words = make_words(
        ("Dormir", 0.0, 0.4), ("mejor.", 0.4, 0.9), ("Hoy", 1.0, 1.3), ("te", 1.3, 1.4), ("cuento", 1.4, 1.9),
    )
    lines = dialogues(build_ass(words, resolve("minimal_mono"), 1080, 1920))
    assert len(lines) == 2
    assert times(lines[0]) == ("0:00:00.00", "0:00:01.00")
    assert event_text(lines[0]) == "Dormir mejor."
    assert event_text(lines[1]) == "Hoy te cuento"


def test_karaoke_mode_emits_one_dialogue_per_word_with_highlight():
    words = make_words(("Dormir", 0.0, 0.5), ("mejor", 0.5, 1.0))
    lines = dialogues(build_ass(words, resolve("bold_karaoke"), 1080, 1920))
    assert len(lines) == 2
    assert times(lines[0]) == ("0:00:00.00", "0:00:00.50")  # hasta el inicio de la palabra siguiente
    assert times(lines[1]) == ("0:00:00.50", "0:00:01.30")  # última palabra: 0.3 s de hold
    assert event_text(lines[0]) == (
        ANIMATION_TAGS["pop"] + "{\\c&H00D4FF&" + WORD_POP + "}Dormir{\\c&HFFFFFF&" + PHRASE_POP + "} mejor"
    )
    assert event_text(lines[1]) == "Dormir {\\c&H00D4FF&" + WORD_POP + "}mejor{\\c&HFFFFFF&\\fscx100\\fscy100}"


def test_karaoke_sweep_emits_kf_per_word_in_one_dialogue():
    words = make_words(("Hola", 0.0, 0.5), ("hoy", 0.5, 0.8))
    lines = dialogues(build_ass(words, resolve("wellness_soft"), 1080, 1920))
    assert len(lines) == 1
    assert event_text(lines[0]) == "{\\fad(80,0)}{\\kf50}Hola {\\kf30}hoy"
    assert times(lines[0]) == ("0:00:00.00", "0:00:01.10")


def test_karaoke_sweep_inserts_an_empty_k_tag_for_the_silence_before_a_word():
    words = make_words(("Hola", 0.0, 0.5), ("hoy", 0.9, 1.2))  # 0.4 s de silencio, mismo grupo
    lines = dialogues(build_ass(words, resolve("wellness_soft"), 1080, 1920))
    assert len(lines) == 1
    assert event_text(lines[0]) == "{\\fad(80,0)}{\\kf50}Hola {\\k40}{\\kf30}hoy"


@pytest.mark.parametrize(("preset", "animation"), [("bold_karaoke", "pop"), ("phrase_box", "fade")])
def test_animation_tag_opens_the_first_event(preset, animation):
    line = dialogues(build_ass(make_words(("Hola", 0, 0.5)), resolve(preset), 1080, 1920))[0]
    assert event_text(line).startswith(ANIMATION_TAGS[animation])


def test_animation_none_adds_no_tags():
    line = dialogues(build_ass(make_words(("Hola", 0, 0.5)), resolve("minimal_mono"), 1080, 1920))[0]
    assert event_text(line) == "Hola"


def test_karaoke_pop_puts_the_phrase_pop_only_on_the_first_event():
    words = make_words(("Dormir", 0.0, 0.5), ("mejor", 0.5, 1.0), ("cada", 1.0, 1.4))
    lines = dialogues(build_ass(words, resolve("bold_karaoke"), 1080, 1920))
    assert len(lines) == 3
    assert event_text(lines[0]).startswith(ANIMATION_TAGS["pop"])
    for line in lines[1:]:
        assert ANIMATION_TAGS["pop"] not in event_text(line)


@pytest.mark.parametrize(("animation", "closing_first", "closing_next"), [
    ("pop", "{\\c&HFFFFFF&" + PHRASE_POP + "}", "{\\c&HFFFFFF&\\fscx100\\fscy100}"),
    ("fade", "{\\c&HFFFFFF&}", "{\\c&HFFFFFF&}"),
    ("none", "{\\c&HFFFFFF&}", "{\\c&HFFFFFF&}"),
])
def test_active_word_closes_without_r_in_every_case(animation, closing_first, closing_next):
    words = make_words(("Dormir", 0.0, 0.5), ("mejor", 0.5, 1.0), ("cada", 1.0, 1.4))
    texts = [event_text(line) for line in dialogues(build_ass(words, resolve("bold_karaoke", {"animation": animation}), 1080, 1920))]
    assert all("\\r" not in text for text in texts)
    assert closing_first in texts[0]
    for text in texts[1:]:
        assert closing_next in text


def test_karaoke_fade_puts_fade_only_on_the_first_event_and_no_word_pop():
    words = make_words(("Dormir", 0.0, 0.5), ("mejor", 0.5, 1.0))
    lines = dialogues(build_ass(words, resolve("bold_karaoke", {"animation": "fade"}), 1080, 1920))
    assert event_text(lines[0]).startswith(ANIMATION_TAGS["fade"])
    assert "{\\fad" not in event_text(lines[1])
    for line in lines:
        assert WORD_POP not in event_text(line)


def test_karaoke_without_animation_has_no_animation_tags():
    words = make_words(("Dormir", 0.0, 0.5), ("mejor", 0.5, 1.0))
    for line in dialogues(build_ass(words, resolve("bold_karaoke", {"animation": "none"}), 1080, 1920)):
        assert "\\fad" not in line
        assert "\\t(" not in line


def test_karaoke_events_are_contiguous_inside_a_group():
    words = make_words(("Dormir", 0.0, 0.4), ("mejor", 0.5, 0.9), ("cada", 0.9, 1.2))
    lines = dialogues(build_ass(words, resolve("bold_karaoke"), 1080, 1920))
    assert [times(line) for line in lines] == [
        ("0:00:00.00", "0:00:00.50"),
        ("0:00:00.50", "0:00:00.90"),
        ("0:00:00.90", "0:00:01.50"),
    ]


def test_last_word_holds_for_0_3_seconds_when_no_next_group_is_close():
    words = make_words(("Dormir.", 0.0, 0.4), ("Mañana", 2.0, 2.5))
    lines = dialogues(build_ass(words, resolve("minimal_mono"), 1080, 1920))
    assert times(lines[0]) == ("0:00:00.00", "0:00:00.70")
    assert times(lines[1]) == ("0:00:02.00", "0:00:02.80")


def test_hold_stops_at_the_start_of_the_next_group():
    words = make_words(("Dormir.", 0.0, 0.4), ("Mañana", 0.5, 0.9))
    lines = dialogues(build_ass(words, resolve("minimal_mono"), 1080, 1920))
    assert times(lines[0]) == ("0:00:00.00", "0:00:00.50")
    assert times(lines[1]) == ("0:00:00.50", "0:00:01.20")


@pytest.mark.parametrize("preset", PRESETS)
def test_sharp_dialogues_never_overlap(preset):
    style = resolve(preset)
    layer = 1 if style["shadow_style"] == "soft" else 0
    lines = dialogues(build_ass(make_words(*SAMPLE), style, 1080, 1920), layer=layer)
    spans = sorted((centis(times(line)[0]), centis(times(line)[1])) for line in lines)
    assert all(start < end for start, end in spans)
    for (_, end), (next_start, _) in zip(spans, spans[1:]):
        assert end <= next_start


def test_uppercase_and_strip_punctuation_change_only_the_display_text():
    style = resolve("bold_caps_pop", {"strip_punctuation": True})
    line = dialogues(build_ass(make_words(("¿Dormir?", 0, 0.5)), style, 1080, 1920))[0]
    assert "DORMIR" in event_text(line)
    assert "¿" not in event_text(line)
    assert "?" not in event_text(line)


def test_braces_in_text_do_not_open_override_tags():
    line = dialogues(build_ass(make_words(("{x}", 0, 0.5)), resolve("minimal_mono"), 1080, 1920))[0]
    assert event_text(line) == "｛x｝"


def test_long_phrase_wraps_with_N_and_keeps_the_last_word_last():
    words = make_words(("Estiramientos", 0, 0.5), ("y", 0.5, 0.6), ("respiración", 0.6, 1.1))
    lines = dialogues(build_ass(words, resolve("bold_karaoke"), 1080, 1920))
    assert len(lines) == 3
    assert event_text(lines[0]).count("\\N") == 1
    assert event_text(lines[0]).endswith("respiración")


def test_single_word_wider_than_the_usable_width_gets_a_fit_scale():
    style = resolve("bold_karaoke")
    assert len(LONG_WORD) == 25
    fit = math.floor(usable_width(style, 1080, 1920) / montserrat_bold_width(LONG_WORD, 96) * 100)
    assert 1 <= fit < 100
    phrase, word = scaled_pop(fit / 100)
    line = dialogues(build_ass(make_words((LONG_WORD, 0.0, 0.5)), style, 1080, 1920), layer=0)[0]
    expected = (f"{{\\fscx{fit}\\fscy{fit}}}" + "{" + phrase + "}"
                + "{\\c&H00D4FF&" + word + "}" + LONG_WORD + "{\\c&HFFFFFF&" + phrase + "}")
    assert event_text(line) == expected


def test_every_event_of_a_group_with_a_wide_word_carries_the_fit_scale():
    style = resolve("bold_karaoke")
    fit = math.floor(usable_width(style, 1080, 1920) / montserrat_bold_width(LONG_WORD, 96) * 100)
    lines = dialogues(build_ass(make_words((LONG_WORD, 0.0, 0.5), ("mejor", 0.5, 1.0)), style, 1080, 1920))
    assert len(lines) == 2
    assert all(event_text(line).startswith(f"{{\\fscx{fit}\\fscy{fit}}}") for line in lines)
    assert f"{{\\c&HFFFFFF&\\fscx{fit}\\fscy{fit}}}" in event_text(lines[1])


def test_fit_scale_applies_without_animation_too():
    style = resolve("bold_karaoke", {"animation": "none"})
    fit = math.floor(usable_width(style, 1080, 1920) / montserrat_bold_width(LONG_WORD, 96) * 100)
    line = dialogues(build_ass(make_words((LONG_WORD, 0.0, 0.5)), style, 1080, 1920))[0]
    assert event_text(line).startswith(f"{{\\fscx{fit}\\fscy{fit}}}")


def test_words_that_fit_get_no_fit_scale():
    line = dialogues(build_ass(make_words(("Dormir", 0, 0.5)), resolve("bold_karaoke"), 1080, 1920))[0]
    assert not event_text(line).startswith("{\\fscx")


def test_soft_shadow_is_a_blurred_copy_below_the_sharp_text():
    words = make_words(("Hola", 0, 0.5), ("hoy", 0.5, 1.0))
    ass = build_ass(words, resolve("ken_classic"), 1080, 1920)
    shadow, sharp = dialogues(ass, layer=0), dialogues(ass, layer=1)
    assert len(shadow) == len(sharp) == 1
    assert event_text(shadow[0]) == "{\\bord0\\shad0\\blur10\\1c&H000000&\\1a&H4D&}{\\fad(80,0)}{\\i1}Hola{\\i0} hoy"
    assert event_text(sharp[0]) == "{\\fad(80,0)}{\\i1}Hola{\\i0} hoy"
    fields = style_fields(ass)
    assert fields[16] == "0"  # sin contorno
    assert fields[17] == "0"  # sin sombra de ASS: la sombra es la capa 0


def test_auto_emphasis_italicizes_the_longest_non_stopword():
    words = make_words(("Hola", 0, 0.5), ("hoy", 0.5, 1.0), ("comparto", 1.0, 1.6))
    sharp = dialogues(build_ass(words, resolve("ken_classic"), 1080, 1920), layer=1)
    assert event_text(sharp[0]) == "{\\fad(80,0)}Hola hoy {\\i1}comparto{\\i0}"


def test_emphasis_flags_in_words_win_over_the_automatic_choice():
    words = [
        {"text": "Hola", "start": 0.0, "end": 0.5},
        {"text": "hoy", "start": 0.5, "end": 1.0, "emph": True},
        {"text": "comparto", "start": 1.0, "end": 1.6, "emph": False},
    ]
    sharp = dialogues(build_ass(words, resolve("ken_classic"), 1080, 1920), layer=1)
    assert event_text(sharp[0]) == "{\\fad(80,0)}Hola {\\i1}hoy{\\i0} comparto"


def test_karaoke_italic_emphasis_puts_the_active_word_in_italics_with_its_colour():
    words = make_words(("Hola", 0.0, 0.5), ("hoy", 0.5, 1.0))
    sharp = dialogues(build_ass(words, resolve("serif_glow"), 1080, 1920), layer=1)
    assert event_text(sharp[0]) == "{\\i1\\c&HA3E7FF&}Hola{\\i0\\c&HFFFFFF&} hoy"
