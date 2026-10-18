import json
from pathlib import Path

import pytest

from engine.ass_builder import build_ass, render_ass
from engine.grouping import line_measure, usable_width
from engine.layout import build_segments, segments_from_phrases
from engine.styles import list_presets, resolve
from engine.timeline import gold_phrases

GOLD = Path(__file__).resolve().parent / "fixtures" / "ken_remedie" / "timelines" / "gold" / "DekXWuPh2T-_gold.json"

SAMPLE = [
    {"text": "Hoy", "start": 0.0, "end": 0.3}, {"text": "te", "start": 0.3, "end": 0.5},
    {"text": "comparto", "start": 0.5, "end": 1.0}, {"text": "tres", "start": 1.0, "end": 1.3},
    {"text": "formas.", "start": 1.3, "end": 1.8}, {"text": "Respira", "start": 2.4, "end": 2.9},
    {"text": "despacio", "start": 2.9, "end": 3.5}, {"text": "y", "start": 3.5, "end": 3.6},
    {"text": "suelta", "start": 3.6, "end": 4.1}, {"text": "los", "start": 4.1, "end": 4.2},
    {"text": "hombros.", "start": 4.2, "end": 4.9}, {"text": "Después", "start": 5.0, "end": 5.5},
    {"text": "duerme", "start": 5.5, "end": 6.0}, {"text": "mejor", "start": 6.0, "end": 6.5},
]


def test_each_segment_has_start_end_lines_fit_and_windows():
    segments = build_segments(SAMPLE, resolve("ken_remedie"), 1080, 1920)
    assert segments
    for segment in segments:
        assert set(segment) == {"start", "end", "lines", "fit", "windows", "layout"}
        assert segment["start"] < segment["end"]
        assert segment["windows"] == []  # ken_remedie es phrase
        for line in segment["lines"]:
            for word in line:
                assert set(word) == {"text", "display", "start", "end", "emph", "index",
                                     "reveal_at", "family", "italic", "size_scale"}
                assert isinstance(word["emph"], bool)


def test_word_indices_follow_the_order_of_the_input():
    segments = build_segments(SAMPLE, resolve("ken_remedie"), 1080, 1920)
    indices = [word["index"] for segment in segments for line in segment["lines"] for word in line]
    assert indices == list(range(len(SAMPLE)))
    for segment in segments:
        for line in segment["lines"]:
            for word in line:
                assert word["text"] == SAMPLE[word["index"]]["text"]


def test_display_applies_uppercase_and_strip_punctuation_but_keeps_the_text():
    style = resolve("ken_remedie", {"uppercase": True, "strip_punctuation": True, "max_chars": 100})
    segment = build_segments([{"text": "formas.", "start": 0, "end": 0.5}], style, 1080, 1920)[0]
    word = segment["lines"][0][0]
    assert (word["text"], word["display"]) == ("formas.", "FORMAS")


def test_fit_is_100_unless_one_word_is_wider_than_the_area():
    normal = build_segments([{"text": "dormir", "start": 0, "end": 0.5}], resolve("minimal_mono"), 1080, 1920)
    assert normal[0]["fit"] == 100
    long_word = [{"text": "supercalifragilisticoexpialidocious", "start": 0, "end": 0.5}]
    wide = build_segments(long_word, resolve("ken_remedie", {"font_size": 300, "max_chars": None}), 1080, 1920)
    assert 1 <= wide[0]["fit"] < 100


def test_karaoke_windows_tile_each_segment_and_end_with_it():
    words = [{"text": "Dormir", "start": 0.0, "end": 0.5}, {"text": "mejor", "start": 0.5, "end": 1.0},
             {"text": "cada", "start": 1.0, "end": 1.4}]
    segments = build_segments(words, resolve("bold_karaoke"), 1080, 1920)
    windows = segments[0]["windows"]
    assert [window["index"] for window in windows] == [0, 1, 2]
    for current, following in zip(windows, windows[1:]):
        assert current["end"] == following["start"]
    assert windows[-1]["end"] == segments[0]["end"]


def test_sweep_windows_are_the_word_spans():
    words = [{"text": "Hola", "start": 0.0, "end": 0.5}, {"text": "hoy", "start": 0.5, "end": 0.8}]
    windows = build_segments(words, resolve("wellness_soft"), 1080, 1920)[0]["windows"]
    assert windows == [{"index": 0, "start": 0.0, "end": 0.5}, {"index": 1, "start": 0.5, "end": 0.8}]


def test_build_ass_is_the_render_of_build_segments():
    style = resolve("ken_remedie")
    segments = build_segments(SAMPLE, style, 720, 1280)
    assert render_ass(segments, style, 720, 1280) == build_ass(SAMPLE, style, 720, 1280)


@pytest.mark.parametrize("preset", [preset["name"] for preset in list_presets()])
def test_segments_never_overlap_in_any_preset(preset):
    segments = build_segments(SAMPLE, resolve(preset), 1080, 1920)
    for current, following in zip(segments, segments[1:]):
        assert current["end"] <= following["start"]


def test_segments_from_phrases_keep_the_given_times():
    phrases = [[{"text": "Hola", "start": 1.0, "end": 1.4}, {"text": "mundo", "start": 1.4, "end": 2.0}],
               [{"text": "fin", "start": 2.5, "end": 2.9}]]
    segments = segments_from_phrases(phrases, resolve("ken_remedie"), 1080, 1920)
    assert [(segment["start"], segment["end"]) for segment in segments] == [(1.0, 2.0), (2.5, 2.9)]
    assert segments[1]["lines"][0][0]["index"] == 2


def test_segments_from_gold_phrases_keep_every_word():
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    phrases = gold_phrases(gold)
    segments = segments_from_phrases(phrases, resolve("ken_remedie"), 1080, 1920)
    assert sum(len(line) for segment in segments for line in segment["lines"]) == sum(len(p) for p in phrases)


def test_a_multi_word_line_wider_than_the_area_is_shrunk_at_font_300():
    style = resolve("ken_remedie", {"font_size": 300})
    sample = [{"text": text, "start": index * 0.3, "end": index * 0.3 + 0.25}
              for index, text in enumerate(["estiramiento", "suave", "para"])]
    segment = build_segments(sample, style, 1080, 1920)[0]
    assert len(segment["lines"]) == 1 and segment["fit"] < 100
    measure, _ = line_measure(style, 1080, 1920)
    width = measure([(word["text"], False) for word in segment["lines"][0]])
    assert width * segment["fit"] / 100 <= usable_width(style, 1080, 1920)


def test_a_line_that_fits_keeps_fit_100_at_the_reference_size():
    sample = [{"text": text, "start": index * 0.3, "end": index * 0.3 + 0.25}
              for index, text in enumerate(["dormir", "mejor"])]
    assert build_segments(sample, resolve("ken_remedie"), 1080, 1920)[0]["fit"] == 100
