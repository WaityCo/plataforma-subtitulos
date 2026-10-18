import pytest

from engine.transcribe import MAX_WORD_MS, MIN_WORD_MS, normalize_words

MIN_S = MIN_WORD_MS / 1000
MAX_S = MAX_WORD_MS / 1000


def test_short_words_get_the_minimum_duration():
    (word,) = normalize_words([("Hola", 1.0, 1.02)])
    assert word["end"] - word["start"] == pytest.approx(MIN_S)


def test_long_words_are_capped_at_the_maximum_duration():
    (word,) = normalize_words([("eeeee", 2.0, 6.0)])
    assert word["end"] - word["start"] == pytest.approx(MAX_S)


def test_overlapping_words_are_pushed_apart():
    words = normalize_words([("uno", 0.0, 0.5), ("dos", 0.3, 0.9), ("tres", 0.4, 0.6)])
    for previous, current in zip(words, words[1:]):
        assert current["start"] >= previous["end"]


def test_every_word_respects_duration_bounds_and_order():
    raw = [("a", 0.0, 0.01), ("b", 0.005, 2.5), ("c", 2.4, 2.45), ("d", 2.46, 3.0)]
    words = normalize_words(raw)
    assert len(words) == 4
    for word in words:
        assert MIN_S - 1e-9 <= word["end"] - word["start"] <= MAX_S + 1e-9
    for previous, current in zip(words, words[1:]):
        assert current["start"] >= previous["end"]


def test_blank_words_are_dropped():
    words = normalize_words([(" ", 0.0, 0.2), ("hola", 0.2, 0.5)])
    assert [word["text"] for word in words] == ["hola"]
