"""Números y cifras que Whisper parte en varios tokens: se unen antes de normalizar los tiempos (F23)."""

import pytest

from engine.transcribe import merge_number_tokens, normalize_words


def test_a_thousands_separator_token_joins_the_number_before_it():
    tokens = [("3", 3.70, 3.78), (".000", 3.78, 3.98), ("euros", 4.00, 4.30)]
    assert merge_number_tokens(tokens) == [("3.000", 3.70, 3.98), ("euros", 4.00, 4.30)]


def test_chained_separators_make_one_number():
    tokens = [("1", 0.0, 0.2), (".000", 0.2, 0.4), (".000", 0.4, 0.6)]
    assert merge_number_tokens(tokens) == [("1.000.000", 0.0, 0.6)]


def test_a_decimal_comma_token_joins_too():
    assert merge_number_tokens([("3", 0.0, 0.2), (",5", 0.2, 0.4)]) == [("3,5", 0.0, 0.4)]


@pytest.mark.parametrize("suffix", ["%", "€", "$"])
def test_a_suffix_token_joins_the_number_before_it(suffix):
    assert merge_number_tokens([("50", 1.0, 1.2), (suffix, 1.2, 1.4)]) == [(f"50{suffix}", 1.0, 1.4)]


def test_a_dollar_before_a_number_joins_it():
    assert merge_number_tokens([("$", 2.0, 2.1), ("5", 2.1, 2.3)]) == [("$5", 2.0, 2.3)]


def test_tokens_that_only_look_like_separators_are_not_joined():
    assert merge_number_tokens([("hola", 0.0, 0.2), (".000", 0.2, 0.4)]) == [("hola", 0.0, 0.2), (".000", 0.2, 0.4)]
    assert merge_number_tokens([("3", 0.0, 0.2), (".", 0.2, 0.3)]) == [("3", 0.0, 0.2), (".", 0.2, 0.3)]
    assert merge_number_tokens([("gracias", 0.0, 0.2), ("%", 0.2, 0.3)]) == [("gracias", 0.0, 0.2), ("%", 0.2, 0.3)]


def test_normalize_joins_the_split_number_and_keeps_its_timing():
    raw = [(" 3", 3.70, 3.78), (" .000", 3.78, 3.98), (" euros", 4.00, 4.30)]
    assert normalize_words(raw) == [
        {"text": "3.000", "start": 3.70, "end": 3.98},
        {"text": "euros", "start": 4.00, "end": 4.30},
    ]
