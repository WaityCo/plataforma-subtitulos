import pytest

from engine.ass_builder import build_ass
from engine.layout import build_segments
from engine.styles import resolve


def words(*items):
    return [{"text": text, "start": start, "end": end} for text, start, end in items]


def dialogues(ass):
    return [line for line in ass.splitlines() if line.startswith("Dialogue: ")]


def layer_of(line):
    return int(line.split(",")[0].split(": ")[1])


def text_of(line):
    return line.split(",", 9)[9]


REVEAL_WORDS = words(("This", 0.0, 0.3), ("is", 0.3, 0.6), ("what", 0.6, 0.9))


def test_reveal_emits_one_text_event_per_word_window_with_the_whole_block():
    text_events = [text_of(line) for line in dialogues(build_ass(REVEAL_WORDS, resolve("huajin_editorial"), 1080, 1920))
                   if layer_of(line) == 1]
    assert len(text_events) == 3
    assert text_events[0].count("\\alpha&HFF&") >= 2  # "is" y "what" aún ocultas
    assert "\\t(0,100,\\1a&H00&" in text_events[0]  # la activa se funde a visible en 100 ms
    assert text_events[2].count("\\alpha&HFF&") == 1  # solo la activa; el resto ya se vio


def test_reveal_without_fade_shows_the_active_word_at_once():
    ass = build_ass(REVEAL_WORDS, resolve("huajin_editorial", {"reveal_fade_ms": 0}), 1080, 1920)
    assert "\\t(0," not in ass


def test_reveal_shadow_copy_fades_to_its_own_alpha_not_to_opaque():
    style = resolve("huajin_editorial")
    copy = [text_of(line) for line in dialogues(build_ass(REVEAL_WORDS, style, 1080, 1920)) if layer_of(line) == 0]
    alpha = f"{round((1 - style['shadow_opacity']) * 255):02X}"
    assert f"\\t(0,100,\\1a&H{alpha}&)" in copy[0]
    assert "\\4a" not in copy[0]


def test_line_events_are_top_anchored_and_left_aligned_at_x_pct():
    ass = build_ass(REVEAL_WORDS, resolve("huajin_editorial"), 720, 1280)
    assert "{\\an7\\pos(57.6," in ass  # 8 % de 720


def test_centered_lines_use_top_center_anchor():
    style = resolve("huajin_editorial", {"text_align": "center", "x_pct": 0.5})
    assert "{\\an8\\pos(360," in build_ass(REVEAL_WORDS, style, 720, 1280)


def test_emphasis_run_switches_family_size_and_spacing_and_restores_the_base():
    emphasized = [dict(word, emph=True) if word["text"] == "is" else word for word in REVEAL_WORDS]
    text = [text_of(line) for line in dialogues(build_ass(emphasized, resolve("huajin_editorial"), 1080, 1920))
            if layer_of(line) == 1][-1]
    assert "\\i1\\fnInstrument Serif\\fs" in text
    assert "\\fsp-2.46" in text  # emphasis_letter_spacing en px de referencia
    assert "\\i0\\fnInter SemiBold\\fs" in text


def test_karaoke_box_draws_one_rounded_rectangle_per_word_window_below_the_text():
    style = resolve("huajin_karaoke_azul")
    page = words(("body", 0, .3), ("to", .3, .6), ("store", .6, .9), ("fat", .9, 1.2))
    dialogue = dialogues(build_ass(page, style, 720, 1280))
    boxes = [line for line in dialogue if layer_of(line) == 0]
    texts = [line for line in dialogue if layer_of(line) > 0]
    assert len(boxes) == 4
    for line in boxes:
        assert "\\p1" in text_of(line) and "\\1c&HEA6F01&" in text_of(line)
        assert " b " in text_of(line)  # esquinas con curvas cúbicas
    assert all(layer_of(line) > 0 for line in texts)


def test_karaoke_box_drawing_ignores_the_style_scale_x_so_the_box_keeps_its_width():
    style = resolve("huajin_karaoke_azul", {"scale_x": 80})
    page = words(("body", 0, .3), ("to", .3, .6))
    boxes = [line for line in dialogues(build_ass(page, style, 720, 1280)) if layer_of(line) == 0]
    assert boxes and all("\\fscx100" in text_of(line) for line in boxes)


def test_karaoke_box_geometry_matches_the_active_word_and_its_padding():
    style = resolve("huajin_karaoke_azul")
    segment = build_segments(words(("body", 0, .3), ("to", .3, .6)), style, 720, 1280)[0]
    word = segment["layout"]["lines"][0]["words"][0]
    box = segment["boxes"][0]
    assert box["x"] == pytest.approx(word["x"] - style["highlight_box_padding_x"])
    assert box["w"] == pytest.approx(word["w"] + 2 * style["highlight_box_padding_x"])
    em = style["font_size"] * 0.56754  # Poppins ExtraBold: px CSS = font_size × css_scale
    assert box["h"] == pytest.approx(em + 2 * style["highlight_box_padding_y"], abs=0.5)
