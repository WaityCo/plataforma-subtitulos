import warnings

import pytest

from engine.styles import display_text, list_presets, resolve

EXPECTED = {
    "ken_remedie": {
        "font_family": "Playfair Display", "font_bold": False, "font_size": 132, "text_color": "#FFFFFF",
        "scale_x": 76, "scale_x_italic": 82, "letter_spacing": -5.25, "word_space_scale": 45,
        "shadow_style": "halo", "outline_width": 3, "shadow_opacity": 0.56, "shadow_blur": 6,
        "y_pct": 0.555, "mode": "phrase", "animation": "none", "max_lines": 1, "max_words_per_line": 4,
        "max_chars": 24, "punctuation_closes": ",.?!:;", "pause_split_s": 0.10, "pause_split_min_words": 2,
        "merge_orphans": False, "target_words": 2, "hang_max_chars": 5, "soft_max_chars": 18,
        "blank_gap_s": 0.30, "tail_s": 0.05, "min_duration_s": 0.30,
        "emphasis": "italic", "emphasis_engine": "lexicon", "emphasis_ratio": 0.30,
    },
    "ken_classic": {
        "font_family": "Instrument Serif", "font_bold": False, "font_size": 92, "text_color": "#FFFFFF",
        "outline_width": 0, "shadow_style": "soft", "shadow_opacity": 0.7, "shadow_blur": 10,
        "alignment": 2, "margin_v": 760, "mode": "phrase", "max_words_per_line": 4, "max_lines": 1,
        "emphasis": "italic", "emphasis_auto": True, "animation": "fade",
    },
    "serif_glow": {
        "font_family": "Instrument Serif", "font_size": 96, "highlight_color": "#FFE7A3", "outline_width": 0,
        "shadow_style": "soft", "shadow_opacity": 0.7, "shadow_blur": 10, "alignment": 2, "margin_v": 700, "mode": "karaoke", "max_words_per_line": 3,
        "max_lines": 1, "emphasis": "italic", "emphasis_auto": False, "animation": "none",
    },
    "bold_karaoke": {
        "font_family": "Montserrat", "font_bold": True, "font_size": 96, "text_color": "#FFFFFF",
        "highlight_color": "#FFD400", "outline_color": "#000000", "outline_width": 8, "shadow_depth": 2,
        "shadow_opacity": 1.0, "alignment": 2, "margin_v": 420, "margin_h": 80, "mode": "karaoke",
        "max_words_per_line": 3, "animation": "pop",
    },
    "phrase_box": {
        "font_family": "Montserrat", "font_bold": True, "font_size": 64, "text_color": "#FFFFFF",
        "box_color": "#000000", "box_opacity": 0.6, "alignment": 5, "mode": "phrase",
        "max_words_per_line": 5, "animation": "fade",
    },
    "bold_caps_pop": {
        "font_family": "Anton", "font_bold": False, "uppercase": True, "font_size": 150,
        "text_color": "#FFFFFF", "highlight_color": "#FFE600", "outline_width": 10, "shadow_opacity": 1.0,
        "alignment": 5, "mode": "karaoke", "max_words_per_line": 1, "animation": "pop",
    },
    "wellness_soft": {
        "font_family": "Poppins SemiBold", "font_bold": False, "font_size": 72, "text_color": "#FFF4E0",
        "highlight_color": "#7FE0C1", "outline_color": "#1B3A33", "outline_width": 4, "shadow_depth": 0,
        "alignment": 5, "mode": "karaoke_sweep", "max_words_per_line": 4, "animation": "fade",
    },
    "minimal_mono": {
        "font_family": "Poppins Medium", "font_bold": False, "font_size": 60, "text_color": "#FFFFFF",
        "outline_width": 3, "shadow_depth": 0, "alignment": 2, "margin_v": 360,
        "mode": "phrase", "max_words_per_line": 6, "animation": "none",
    },
}


@pytest.mark.parametrize("name", list(EXPECTED))
def test_preset_values_match_the_spec(name):
    style = resolve(name)
    for key, value in EXPECTED[name].items():
        assert style[key] == value, key


def test_presets_file_has_the_eight_previous_presets_then_the_three_hua_jin_ones_with_text_fields():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        presets = list_presets()
    hua_jin = ["huajin_editorial", "huajin_karaoke_azul", "huajin_basico"]
    assert [preset["name"] for preset in presets] == [*EXPECTED, *hua_jin]
    assert len(presets) == 11
    for preset in presets:
        assert preset["label"].strip()
        assert preset["description"].strip()
        assert set(preset["style"]) == set(resolve("ken_classic"))


def test_ken_remedie_is_the_first_preset_with_its_label():
    presets = list_presets()
    assert presets[0]["name"] == "ken_remedie"
    assert presets[0]["label"] == "Ken Remedie"


def test_ken_classic_keeps_its_id_and_gets_the_editorial_label():
    preset = next(item for item in list_presets() if item["name"] == "ken_classic")
    assert preset["label"] == "Serif editorial"
    assert resolve("ken_classic")["font_family"] == "Instrument Serif"


def test_new_fields_default_to_the_behaviour_of_the_previous_presets():
    style = resolve("minimal_mono")
    assert (style["scale_x"], style["scale_x_italic"], style["letter_spacing"], style["word_space_scale"]) == (
        100, None, 0, 100)
    assert (style["y_pct"], style["max_chars"], style["punctuation_closes"]) == (None, None, ".?!")
    assert (style["pause_split_s"], style["pause_split_min_words"], style["merge_orphans"]) == (0.6, 1, False)
    assert (style["blank_gap_s"], style["tail_s"], style["min_duration_s"]) == (None, 0.05, 0.30)
    assert (style["emphasis_engine"], style["emphasis_ratio"]) == ("length", None)


@pytest.mark.parametrize("overrides", [
    {"text_color": "white"},
    {"text_color": "#FFF"},
    {"highlight_color": "#GGGGGG"},
    {"box_color": "000000"},
    {"shadow_color": "black"},
])
def test_invalid_color_raises(overrides):
    with pytest.raises(ValueError, match="#RRGGBB"):
        resolve("ken_classic", overrides)


@pytest.mark.parametrize("overrides", [
    {"mode": "karaoke2"},
    {"animation": "spin"},
    {"alignment": 0},
    {"alignment": 10},
    {"emphasis": "bold"},
    {"shadow_style": "glow"},
])
def test_invalid_enumeration_or_range_raises(overrides):
    with pytest.raises(ValueError):
        resolve("ken_classic", overrides)


@pytest.mark.parametrize("overrides", [
    {"font_size": "86"},
    {"font_bold": 1},
    {"max_words_per_line": 2.5},
    {"font_size": 2},
    {"box_opacity": 1.5},
    {"margin_v": -1},
    {"outline_width": True},
    {"font_size": float("nan")},
    {"font_family": ""},
    {"font_family": "Mon,tserrat"},
    {"shadow_opacity": 1.5},
    {"shadow_blur": -1},
    {"emphasis_auto": "yes"},
])
def test_invalid_type_or_range_raises(overrides):
    with pytest.raises(ValueError):
        resolve("ken_classic", overrides)


def test_unknown_field_warns_and_is_ignored():
    with pytest.warns(UserWarning, match="desconocido"):
        style = resolve("ken_classic", {"font_colour": "#000000"})
    assert "font_colour" not in style


def test_overrides_win_over_the_preset_and_keep_the_rest():
    style = resolve("minimal_mono", {"font_size": 70, "box_color": None})
    assert style["font_size"] == 70
    assert style["font_family"] == "Poppins Medium"
    assert style["box_color"] is None


def test_unknown_preset_raises():
    with pytest.raises(ValueError, match="Preset desconocido"):
        resolve("no_existe")


def test_overrides_must_be_a_mapping():
    with pytest.raises(ValueError):
        resolve("ken_classic", ["font_size", 90])


def test_resolve_returns_a_fresh_dict():
    first = resolve("ken_classic")
    first["font_size"] = 1
    assert resolve("ken_classic")["font_size"] == 92


def test_display_text_uppercases_and_strips_punctuation_when_asked():
    style = resolve("bold_caps_pop", {"strip_punctuation": True})
    assert display_text("¿Dormir?", style) == "DORMIR"
    assert display_text("mejor.", resolve("minimal_mono")) == "mejor."
