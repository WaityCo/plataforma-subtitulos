import json
from pathlib import Path

import pytest

from engine.layout import build_segments, segments_from_blocks
from engine.styles import resolve
from engine.timeline import gold_blocks

GOLD = Path(__file__).resolve().parent / "fixtures" / "hua_jin" / "A_gold_DeVJxzpgPHL.json"
# Medido: 16 de 22 fronteras del gold salen iguales (72,7 %) y hay 15 palabras en serif, como en el gold.
BOUNDARY_RECALL_MIN = 0.70
SERIF_TOLERANCE = 1


def words(*items):
    return [{"text": text, "start": start, "end": end} for text, start, end in items]


SAMPLE = words(("This", 0.0, 0.3), ("is", 0.3, 0.6), ("what", 0.6, 0.9), ("cinnamon", 0.9, 1.4),
               ("does", 1.5, 1.8), ("to", 1.8, 2.0), ("the", 2.0, 2.2), ("sugar", 2.2, 2.7))


def test_words_carry_family_italic_size_scale_and_reveal_at():
    segments = build_segments(SAMPLE, resolve("huajin_editorial", {"emphasis_engine": "length"}), 720, 1280)
    flat = [word for segment in segments for line in segment["lines"] for word in line]
    emphasized = [word for word in flat if word["emph"]]
    plain = [word for word in flat if not word["emph"]]
    assert emphasized and plain
    assert all(word["family"] == "Instrument Serif" and word["italic"] and word["size_scale"] == 1.55
               for word in emphasized)
    assert all(word["family"] == "Inter SemiBold" and not word["italic"] and word["size_scale"] == 1.0
               for word in plain)
    assert all(word["reveal_at"] == word["start"] for word in flat)


def test_reveal_windows_are_contiguous_and_the_last_one_ends_with_the_block():
    segments = build_segments(SAMPLE, resolve("huajin_editorial"), 720, 1280)
    for segment in segments:
        windows = segment["windows"]
        assert windows
        for current, following in zip(windows, windows[1:]):
            assert current["end"] == following["start"]
        assert windows[-1]["end"] == segment["end"]


def test_karaoke_box_segments_carry_one_box_per_window():
    segments = build_segments(SAMPLE, resolve("huajin_karaoke_azul"), 720, 1280)
    for segment in segments:
        assert [box["index"] for box in segment["boxes"]] == [window["index"] for window in segment["windows"]]
        assert all({"x", "y", "w", "h"} <= set(box) for box in segment["boxes"])


def test_layout_anchor_follows_x_pct_and_y_pct_in_reference_pixels():
    segment = build_segments(SAMPLE, resolve("huajin_editorial"), 720, 1280)[0]
    anchor = segment["layout"]["anchor"]
    assert anchor["x"] == pytest.approx(0.08 * 1080)  # 720 px de ancho / escala 0.6667 = 1080 de referencia
    assert anchor["y"] == pytest.approx(0.52 * 1920)
    assert anchor["align"] == "left"


def test_gold_a_blocks_keep_their_words_lines_and_scales():
    blocks = gold_blocks(json.loads(GOLD.read_text(encoding="utf-8")))
    assert len(blocks) == 22
    segments = segments_from_blocks(blocks, resolve("huajin_editorial"), 720, 1280)
    assert [len(segment["lines"]) for segment in segments] == [len(block["lines"]) for block in blocks]
    assert [sum(len(line) for line in segment["lines"]) for segment in segments] == [len(block["words"]) for block in blocks]
    assert segments[0]["fit"] == round(blocks[0]["scale"] * 100)


def test_automatic_segmentation_of_the_gold_recovers_most_block_boundaries():
    blocks = gold_blocks(json.loads(GOLD.read_text(encoding="utf-8")))
    gold_words = [word for block in blocks for word in block["words"]]
    plain = [{"text": word["text"], "start": word["start"], "end": word["end"]} for word in gold_words]
    segments = build_segments(plain, resolve("huajin_editorial"), 720, 1280)
    gold_ends, ours_ends, position = set(), set(), -1
    for block in blocks:
        position += len(block["words"])
        gold_ends.add(position)
    position = -1
    for segment in segments:
        position += sum(len(line) for line in segment["lines"])
        ours_ends.add(position)
    recall = len(gold_ends & ours_ends) / len(gold_ends)
    assert recall >= BOUNDARY_RECALL_MIN


def test_serif_word_count_of_the_automatic_segmentation_is_close_to_the_gold():
    blocks = gold_blocks(json.loads(GOLD.read_text(encoding="utf-8")))
    gold_serif = sum(1 for block in blocks for word in block["words"] if word["emph"])
    plain = [{"text": word["text"], "start": word["start"], "end": word["end"]}
             for block in blocks for word in block["words"]]
    segments = build_segments(plain, resolve("huajin_editorial"), 720, 1280)
    ours_serif = sum(1 for segment in segments for line in segment["lines"] for word in line if word["emph"])
    assert abs(ours_serif - gold_serif) <= SERIF_TOLERANCE
