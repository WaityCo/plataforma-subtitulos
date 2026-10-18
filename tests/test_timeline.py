import json
from pathlib import Path

import pytest

from engine.ass_builder import render_ass
from engine.styles import resolve
from engine.timeline import gold_phrases, markup_from_segments, segments_from_markup, words_from_markup

GOLD = Path(__file__).resolve().parent / "fixtures" / "ken_remedie" / "timelines" / "gold" / "DekXWuPh2T-_gold.json"


@pytest.fixture(scope="module")
def gold():
    return json.loads(GOLD.read_text(encoding="utf-8"))


def phrase_texts(gold_data):
    return [" ".join(word["text"] for word in phrase) for phrase in gold_phrases(gold_data)]


def test_pauses_are_skipped_and_the_slash_splits_one_segment_into_two_phrases(gold):
    texts = phrase_texts(gold)
    assert "Your chin sags" in texts and "like this?" in texts
    assert all("/" not in text for text in texts)
    assert not any(word["text"] == "/" for word in words_from_markup(gold))


def test_the_first_phrase_spans_its_segment_and_splits_time_by_characters(gold):
    first = gold_phrases(gold)[0]
    assert [word["text"] for word in first] == ["If", "your", "socks"]
    assert first[0]["start"] == 0.0
    assert first[-1]["end"] == pytest.approx(0.767)
    assert first[0]["end"] == pytest.approx(0.767 * 2 / 11, abs=1e-6)  # "If" tiene 2 de 11 caracteres


def test_asterisks_mark_italic_words_including_multi_word_runs(gold):
    italics = [word["text"] for word in words_from_markup(gold) if word["emph"]]
    assert italics[:3] == ["socks", "backed-up", "jeans"]
    assert "\"TEA\"" in italics and "health" in italics and "protocols" in italics
    assert "that's" not in italics


def test_segments_from_markup_keep_the_gold_phrases_and_emphasis(gold):
    segments = segments_from_markup(gold, resolve("ken_remedie"), 720, 1280)
    assert len(segments) == len(gold_phrases(gold))
    first = segments[0]
    assert (first["start"], first["end"]) == (0.0, pytest.approx(0.767))
    assert [word["text"] for word in first["lines"][0]] == ["If", "your", "socks"]
    assert [word["emph"] for word in first["lines"][0]] == [False, False, True]
    assert first["lines"][0][2]["index"] == 2


def test_markup_round_trips_through_segments_for_every_gold_phrase(gold):
    expected = []
    for segment in gold["segments"]:
        if segment.get("markup"):
            expected.extend(part.strip() for part in segment["markup"].split(" / "))
    exported = markup_from_segments(segments_from_markup(gold))
    assert [item["markup"] for item in exported] == expected


def test_exported_times_match_the_gold_to_the_millisecond(gold):
    exported = markup_from_segments(segments_from_markup(gold))
    gold_spans = [(phrase[0]["start"], phrase[-1]["end"]) for phrase in gold_phrases(gold)]
    assert [(round(item["start"], 3), round(item["end"], 3)) for item in exported] == [
        (round(start, 3), round(end, 3)) for start, end in gold_spans]


def test_gold_segments_render_with_the_reference_tags(gold):
    style = resolve("ken_remedie", {"y_pct": 0.554})
    ass = render_ass(segments_from_markup(gold, style, 720, 1280), style, 720, 1280)
    first = next(line for line in ass.splitlines() if line.startswith("Dialogue: "))
    assert first.endswith(
        "{\\pos(360,709)\\blur4\\fsp-3.5}If{\\fscx45} {\\fscx76}your{\\fscx45} {\\fscx76}{\\i1\\fscx82}socks{\\i0\\fscx76}")
