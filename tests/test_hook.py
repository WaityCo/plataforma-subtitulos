from pathlib import Path

import pytest
from PIL import Image

from engine import burn as burn_module
from engine import pipeline
from engine.hook import MEDIUM, _clusters, _emoji_font, _emoji_image, _pieces, render_hook, validate_spec

SPEC = {
    "headline": "The number 1 food causing high blood pressure in the USA ‼️⚠️",
    "news_title": "BREAKING NEWS",
    "news_subtitle": "Health Concerns",
    "duration_s": 3,
}


def test_validate_spec_rejects_a_missing_headline_and_a_bad_duration():
    with pytest.raises(ValueError, match="headline"):
        validate_spec({"headline": "  ", "duration_s": 2})
    with pytest.raises(ValueError, match="duration_s"):
        validate_spec({"headline": "x", "duration_s": 11})
    with pytest.raises(ValueError, match="kicker"):
        validate_spec({"headline": "x", "duration_s": 2, "kicker": 3})


def test_render_hook_writes_the_pill_and_both_news_bars_with_their_timing(tmp_path):
    elements = render_hook(SPEC, 720, 1280, out_dir=tmp_path)
    assert [path.name for path, *_ in elements] == ["hook_pill.png", "hook_news_title.png", "hook_news_subtitle.png"]
    for path, start, end, _x, _y in elements:
        assert path.is_file()
        assert (start, end) == (0.0, 3.0)


def test_pill_is_87_percent_of_the_width_centered_and_starts_at_43_percent_of_the_height(tmp_path):
    path, _start, _end, x, y = render_hook(SPEC, 720, 1280, out_dir=tmp_path)[0]
    image = Image.open(path)
    assert image.width == round(720 * 0.87)
    assert x == (720 - image.width) // 2
    assert y == round(1280 * 0.43)


def test_a_kicker_is_drawn_above_the_pill(tmp_path):
    elements = render_hook(dict(SPEC, kicker="Listen carefully"), 720, 1280, out_dir=tmp_path)
    names = {path.name: y for path, _s, _e, _x, y in elements}
    assert names["hook_kicker.png"] < names["hook_pill.png"]


def test_burn_superposes_each_overlay_after_the_ass_filter_with_its_window():
    cmd = burn_module._command(Path("in.mp4"), Path("out.mp4"), None, [("overlay_0.png", 0.0, 3.0, 47, 550)], 5.0)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert graph == "[0:v]ass=subtitles.ass:fontsdir=fonts[v0];[v0][1:v]overlay=47:550:enable='between(t,0,3)'[v1]"
    assert cmd[cmd.index("-map") + 1] == "[v1]"
    assert cmd[cmd.index("-loop") + 1] == "1"
    assert cmd[cmd.index("-t") + 1] == "5"  # un PNG en bucle no termina solo: la salida se corta con el video


def test_burn_without_overlays_keeps_the_plain_video_filter():
    cmd = burn_module._command(Path("in.mp4"), Path("out.mp4"), None, (), 5.0)
    assert "-filter_complex" not in cmd and "-loop" not in cmd
    assert cmd[cmd.index("-vf") + 1] == "ass=subtitles.ass:fontsdir=fonts"


def run_hook_job(monkeypatch, tmp_path, hook):
    """run_job con burn=True y un quemado falso. Devuelve el resultado y los overlays que recibió burn."""
    video = tmp_path / "in.mp4"
    video.write_bytes(b"no es un video real")
    captured = {}

    def fake_burn(video_path, ass_text, output, fonts_dir, preview_seconds=None, progress=None, overlays=()):
        captured["overlays"] = list(overlays)

    monkeypatch.setattr(pipeline, "probe_video", lambda path: {"width": 720, "height": 1280, "duration": 5.0})
    monkeypatch.setattr(pipeline, "has_audio", lambda path: True)
    monkeypatch.setattr(pipeline, "extract_audio", lambda video_path, wav_path: None)
    monkeypatch.setattr(pipeline, "transcribe", lambda wav_path, language=None, model_size="small": words_for_job())
    monkeypatch.setattr(pipeline, "is_available", lambda: True)
    monkeypatch.setattr(pipeline, "burn_video", fake_burn)
    result = pipeline.run_job(video, tmp_path / "job", preset="huajin_editorial", burn=True, hook=hook)
    return result, captured["overlays"]


def test_run_job_hands_the_hook_overlays_to_burn(monkeypatch, tmp_path):
    _result, overlays = run_hook_job(monkeypatch, tmp_path, SPEC)
    assert len(overlays) == 3
    assert all(Path(png).parent == tmp_path / "job" / "hook" for png, *_ in overlays)


def test_run_job_returns_the_hook_warnings(monkeypatch, tmp_path):
    result, _overlays = run_hook_job(monkeypatch, tmp_path, dict(SPEC, headline="Antes  después"))
    assert result["hook_warnings"] == ["Sin glifo en ninguna fuente, omitido: U+E000"]


def words_for_job():
    return [{"text": "Drink", "start": 0.0, "end": 0.4}, {"text": "this", "start": 0.4, "end": 0.7}]


def test_color_emoji_font_is_found_on_this_system():
    if _emoji_font() is None:
        pytest.skip("sin fuente de emoji a color en este sistema")
    assert _emoji_font()[1] in (160, 109)


FIRE = "\U0001F525"
FLAG = "\U0001F1E8\U0001F1F4"
FAMILY = "\U0001F468‍\U0001F469‍\U0001F467"
WARNING = "‼️"
CAUTION = "⚠️"
ACCENT = "á"
needs_emoji_font = pytest.mark.skipif(_emoji_font() is None, reason="sin fuente de emoji a color en este sistema")


def colored_pixels(image):
    """Píxeles visibles y saturados: un emoji a color los tiene y una caja de glifo que falta no."""
    rgba = image.convert("RGBA")
    return sum(
        count
        for count, (red, green, blue, alpha) in rgba.getcolors(rgba.width * rgba.height)
        if alpha and max(red, green, blue) - min(red, green, blue) > 40
    )


def test_graphemes_keep_flags_families_and_marks_together():
    assert _clusters(FLAG) == [FLAG]
    assert _clusters(FAMILY) == [FAMILY]
    assert _clusters(WARNING + CAUTION) == [WARNING, CAUTION]
    assert _clusters(ACCENT) == ["á"]


@needs_emoji_font
@pytest.mark.parametrize("emoji", [FIRE, FLAG, FAMILY, WARNING, CAUTION])
def test_each_emoji_is_one_piece_for_the_color_font(emoji):
    warnings = []
    assert _pieces(emoji, MEDIUM, warnings) == [("emoji", emoji)]
    assert warnings == []


def test_accented_letters_stay_in_the_text_font():
    assert _pieces(ACCENT, MEDIUM, []) == [("text", "á")]
    assert _pieces("hola" + FIRE, MEDIUM, []) == [("text", "hola"), ("emoji", FIRE)]


@needs_emoji_font
@pytest.mark.parametrize("emoji", [FIRE, FLAG, FAMILY])
def test_color_emoji_are_drawn_in_colour_not_as_empty_boxes(emoji):
    image = _emoji_image(emoji, 60)
    assert image is not None and image.height == 60
    assert colored_pixels(image) > 500


def test_a_grapheme_without_glyph_in_any_font_is_omitted_and_reported(tmp_path):
    elements = render_hook({"headline": "Antes  después", "duration_s": 2}, 720, 1280, out_dir=tmp_path)
    assert elements.warnings == ["Sin glifo en ninguna fuente, omitido: U+E000"]
    assert [path.name for path, *_ in elements] == ["hook_pill.png"]


@needs_emoji_font
def test_emoji_and_accents_in_every_hook_text_draw_without_warnings(tmp_path):
    spec = {
        "headline": f"Café {FIRE} para {FLAG} la familia {FAMILY} {WARNING} {CAUTION} á",
        "kicker": f"{FIRE} Escucha",
        "news_title": f"{FLAG} última hora",
        "news_subtitle": "Salud á",
        "duration_s": 3,
    }
    elements = render_hook(spec, 720, 1280, out_dir=tmp_path)
    assert elements.warnings == []
    paths = {path.name: path for path, *_ in elements}
    with Image.open(paths["hook_pill.png"]) as pill:
        assert colored_pixels(pill) > 500
    with Image.open(paths["hook_kicker.png"]) as kicker:
        assert colored_pixels(kicker) > 500
