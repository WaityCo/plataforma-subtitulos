import shutil

import pytest
from fontTools.ttLib import TTFont

import engine.textmetrics as textmetrics
from engine.textmetrics import FONTS_DIR, font_catalog, font_file, text_width

FIELDS = {
    "family", "bold", "italic", "file", "units_per_em", "ascent", "descent",
    "win_ascent", "win_descent", "css_scale", "line_height",
}
CACHES = (textmetrics._static_files, textmetrics.font_file, textmetrics._tables)


def by_file():
    return {entry["file"]: entry for entry in font_catalog()}


@pytest.fixture
def clean_caches():
    """Vacía las cachés de textmetrics al entrar y al salir, por si FONTS_DIR cambió en medio."""
    for cached in CACHES:
        cached.cache_clear()
    yield
    for cached in CACHES:
        cached.cache_clear()


def test_one_entry_per_static_font_and_no_variable_font():
    files = [entry["file"] for entry in font_catalog()]
    expected = sorted(
        path.name for path in FONTS_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in (".ttf", ".otf") and "[" not in path.name
    )
    assert files == expected
    assert len(files) == 13  # 9 previas (7 de los presets + Playfair Display 500) + Inter SemiBold, Montserrat Medium, Poppins ExtraBold y Poppins Bold (ronda B; ningún preset lo usa)
    assert "Montserrat[wght].ttf" not in files
    assert "PlayfairDisplay[wght].ttf" not in files
    assert "PlayfairDisplay-Italic[wght].ttf" not in files


def test_otf_files_are_cataloged_and_measured_like_ttf(tmp_path, monkeypatch, clean_caches):
    # assets/fonts no trae ningún OTF. El archivo de prueba lleva contenido TTF con extensión .otf;
    # fontTools lee ambos por la cabecera, así que sirve para probar el filtro y la medida.
    shutil.copy2(FONTS_DIR / "Montserrat-Bold.ttf", tmp_path / "Probe.otf")
    monkeypatch.setattr(textmetrics, "FONTS_DIR", tmp_path)
    catalog = font_catalog()
    assert [entry["file"] for entry in catalog] == ["Probe.otf"]
    assert catalog[0]["family"] == "Montserrat" and catalog[0]["bold"] is True
    assert font_file("Montserrat", True).name == "Probe.otf"
    with TTFont(FONTS_DIR / "Montserrat-Bold.ttf") as font:
        cmap, hmtx, upem = font.getBestCmap(), font["hmtx"], font["head"].unitsPerEm
        expected = sum(hmtx[cmap[ord(char)]][0] for char in "Hola") * 86 / upem
    assert text_width("Hola", "Montserrat", True, 86) == pytest.approx(expected)


def test_entries_have_the_required_fields():
    for entry in font_catalog():
        assert set(entry) == FIELDS


def test_metrics_are_read_from_the_font_files():
    for entry in font_catalog():
        with TTFont(FONTS_DIR / entry["file"]) as font:
            assert entry["units_per_em"] == font["head"].unitsPerEm
            assert entry["ascent"] == font["hhea"].ascent
            assert entry["descent"] == font["hhea"].descent
            assert entry["win_ascent"] == font["OS/2"].usWinAscent
            assert entry["win_descent"] == font["OS/2"].usWinDescent


def test_css_scale_is_units_per_em_over_the_win_height():
    for entry in font_catalog():
        expected = entry["units_per_em"] / (entry["win_ascent"] + entry["win_descent"])
        assert entry["css_scale"] == pytest.approx(expected)


def test_css_scale_values_from_the_measured_metrics():
    catalog = by_file()
    assert catalog["InstrumentSerif-Regular.ttf"]["css_scale"] == pytest.approx(0.7692, abs=1e-4)
    assert catalog["Montserrat-Bold.ttf"]["css_scale"] == pytest.approx(0.6402, abs=1e-4)
    assert catalog["Anton-Regular.ttf"]["css_scale"] == pytest.approx(0.5769, abs=1e-4)


def test_line_height_is_one_font_size_because_libass_fits_the_win_height():
    for entry in font_catalog():
        assert entry["line_height"] == pytest.approx(1.0)


def test_family_and_style_flags_follow_the_lookup_names():
    catalog = by_file()
    assert (catalog["Montserrat-Bold.ttf"]["family"], catalog["Montserrat-Bold.ttf"]["bold"],
            catalog["Montserrat-Bold.ttf"]["italic"]) == ("Montserrat", True, False)
    assert (catalog["Montserrat-ExtraBold.ttf"]["family"], catalog["Montserrat-ExtraBold.ttf"]["bold"]) == (
        "Montserrat ExtraBold", False)
    assert (catalog["InstrumentSerif-Italic.ttf"]["family"], catalog["InstrumentSerif-Italic.ttf"]["italic"]) == (
        "Instrument Serif", True)
    assert catalog["Anton-Regular.ttf"]["family"] == "Anton"
