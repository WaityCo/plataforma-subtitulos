"""Playfair Display de ken_remedie: las estáticas son las que miden y queman, y libass las elige por familia."""

import shutil
import subprocess

import numpy as np
import pytest

from engine.burn import is_available
from engine.ffbin import ffmpeg_bin
from engine.textmetrics import FONTS_DIR, font_catalog, font_file
from libass_probe import _alias_copy

REGULAR = FONTS_DIR / "PlayfairDisplay-Medium500-static.ttf"
ITALIC = FONTS_DIR / "PlayfairDisplay-Italic500-static.ttf"


def test_playfair_statics_are_the_files_measured_for_ken():
    assert font_file("Playfair Display", False, False).name == REGULAR.name
    assert font_file("Playfair Display", False, True).name == ITALIC.name


def test_playfair_statics_are_weight_500_regular_and_italic():
    catalog = {entry["file"]: entry for entry in font_catalog()}
    assert (catalog[REGULAR.name]["family"], catalog[REGULAR.name]["bold"], catalog[REGULAR.name]["italic"]) == (
        "Playfair Display", False, False)
    assert (catalog[ITALIC.name]["family"], catalog[ITALIC.name]["italic"]) == ("Playfair Display", True)


def test_playfair_variables_stay_out_of_measure_and_burn_but_ship_for_css():
    names = {entry["file"] for entry in font_catalog()}
    assert "PlayfairDisplay[wght].ttf" not in names
    assert "PlayfairDisplay-Italic[wght].ttf" not in names
    assert (FONTS_DIR / "PlayfairDisplay[wght].ttf").is_file()
    assert (FONTS_DIR / "OFL-PlayfairDisplay.txt").is_file()


def _ass(family, italic=False):
    body = ("{\\i1}" if italic else "") + "Hamburgefonstiv"
    return ("[Script Info]\nScriptType: v4.00+\nPlayResX: 720\nPlayResY: 1280\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
            "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
            "MarginR, MarginV, Encoding\n"
            f"Style: Default,{family},132,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            f"Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,{{\\pos(360,640)}}{body}\n")


def _render(ass_text, fontsdir, workdir):
    (workdir / "subtitles.ass").write_text(ass_text, encoding="utf-8")
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=720x1280:d=1",
           "-vf", f"ass=subtitles.ass:fontsdir={fontsdir}", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    return np.frombuffer(subprocess.run(cmd, cwd=workdir, capture_output=True, check=True).stdout, np.uint8)


@pytest.mark.skipif(not is_available(), reason="ffmpeg sin libass")
def test_libass_resolves_playfair_display_to_the_static_files(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    shutil.copy2(REGULAR, real / REGULAR.name)
    shutil.copy2(ITALIC, real / ITALIC.name)
    alias = tmp_path / "alias"
    alias.mkdir()
    _alias_copy(REGULAR, alias / "CalibMedium.ttf", "CalibMedium")
    _alias_copy(ITALIC, alias / "CalibItalic.ttf", "CalibItalic")
    work = tmp_path / "work"
    work.mkdir()
    assert np.array_equal(_render(_ass("Playfair Display"), real, work), _render(_ass("CalibMedium"), alias, work))
    assert np.array_equal(_render(_ass("Playfair Display", True), real, work),
                          _render(_ass("CalibItalic", True), alias, work))
