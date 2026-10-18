import pytest
from fontTools.ttLib import TTFont

from engine.styles import list_presets, resolve
from engine.textmetrics import FONTS_DIR, font_file, text_width

PRESET_NAMES = [preset["name"] for preset in list_presets()]


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_every_preset_font_resolves_to_a_static_file(preset):
    style = resolve(preset)
    path = font_file(style["font_family"], style["font_bold"], style["emphasis"] in ("italic", "italic_color"))
    assert path is not None
    assert "[" not in path.name


def test_static_montserrat_names_are_found_by_family_and_weight():
    assert font_file("Montserrat", True).name == "Montserrat-Bold.ttf"
    assert font_file("Montserrat ExtraBold", False).name == "Montserrat-ExtraBold.ttf"


def test_montserrat_without_bold_is_measured_with_bold_never_with_the_variable_font():
    assert font_file("Montserrat", False).name == "Montserrat-Bold.ttf"
    assert "[" not in font_file("Montserrat", False).name


def test_instrument_serif_italic_is_found_and_changes_the_width():
    assert font_file("Instrument Serif", False, True).name == "InstrumentSerif-Italic.ttf"
    regular = text_width("Estiramientos", "Instrument Serif", False, 92)
    italic = text_width("Estiramientos", "Instrument Serif", False, 92, italic=True)
    assert regular != italic


def test_variable_montserrat_is_kept_for_the_frontend():
    assert (FONTS_DIR / "Montserrat[wght].ttf").is_file()


def test_text_width_sums_font_advances_scaled_to_font_size():
    with TTFont(FONTS_DIR / "Montserrat-Bold.ttf") as font:
        cmap, hmtx, upem = font.getBestCmap(), font["hmtx"], font["head"].unitsPerEm
        units = sum(hmtx[cmap[ord(char)]][0] for char in "Hola")
    assert text_width("Hola", "Montserrat", True, 86) == pytest.approx(units * 86 / upem)


def test_missing_font_falls_back_to_0_6_em_per_character():
    assert text_width("abcd", "Fuente que no existe", False, 100) == pytest.approx(240)
