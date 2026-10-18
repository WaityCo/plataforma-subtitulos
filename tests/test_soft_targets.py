"""Topes blandos de la frase: target_words, hang_max_chars y soft_max_chars. Los topes duros no cambian."""

import pytest

from engine.grouping import group_words
from engine.styles import resolve

PLAIN = {"emphasis": "none", "max_chars": None, "soft_max_chars": None, "target_words": None,
         "hang_max_chars": 0, "merge_orphans": False, "pause_split_s": 5, "max_words_per_line": 4}


def words(*texts):
    return [{"text": text, "start": 0.2 * index, "end": 0.2 * index + 0.15} for index, text in enumerate(texts)]


def groups(sample, **overrides):
    style = resolve("ken_remedie", {**PLAIN, **overrides})
    return [[word["text"] for word in group["words"]] for group in group_words(sample, style, 1080, 1920)]


def test_without_soft_targets_the_hard_word_limit_still_cuts_at_four():
    assert groups(words("a", "bb", "cc", "dd", "ee")) == [["a", "bb", "cc", "dd"], ["ee"]]


def test_target_words_cuts_once_the_phrase_reaches_the_target():
    assert groups(words("one", "two", "three", "four", "five", "six"), target_words=3) == [
        ["one", "two", "three"], ["four", "five", "six"]]


def test_a_short_word_hangs_at_the_end_when_the_phrase_is_at_the_target():
    assert groups(words("one", "two", "in", "four", "five"), target_words=2, hang_max_chars=2) == [
        ["one", "two", "in"], ["four", "five"]]


def test_a_long_word_still_opens_the_next_phrase():
    assert groups(words("one", "two", "three", "four"), target_words=2, hang_max_chars=2) == [
        ["one", "two"], ["three", "four"]]


def test_hanging_does_not_chain_past_the_target():
    assert groups(words("one", "two", "in", "on", "five"), target_words=2, hang_max_chars=2) == [
        ["one", "two", "in"], ["on", "five"]]


def test_soft_max_chars_cuts_before_the_limit_is_passed():
    assert groups(words("alpha", "bravo", "charlie"), soft_max_chars=11) == [["alpha", "bravo"], ["charlie"]]


def test_soft_max_chars_lets_a_short_word_hang_within_the_hard_limit():
    assert groups(words("alpha", "bravo", "of", "charlie"), soft_max_chars=11, hang_max_chars=2) == [
        ["alpha", "bravo", "of"], ["charlie"]]


def test_the_hard_limits_win_over_the_soft_ones():
    assert groups(words("alpha", "bravo", "of", "the", "end"), target_words=10, max_words_per_line=2) == [
        ["alpha", "bravo"], ["of", "the"], ["end"]]


def test_a_pause_still_cuts_when_the_soft_target_is_not_reached():
    sample = [{"text": "one", "start": 0.0, "end": 0.2}, {"text": "two", "start": 0.2, "end": 0.4},
              {"text": "three", "start": 0.9, "end": 1.1}]
    assert groups(sample, target_words=5, pause_split_s=0.3, pause_split_min_words=2) == [
        ["one", "two"], ["three"]]


@pytest.mark.parametrize("overrides", [
    {"target_words": 0},
    {"hang_max_chars": -1},
    {"hang_max_chars": 11},
    {"soft_max_chars": 0},
])
def test_invalid_soft_target_values_are_rejected(overrides):
    with pytest.raises(ValueError):
        resolve("ken_remedie", overrides)
