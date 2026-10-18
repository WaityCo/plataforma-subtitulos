import json

from engine.stopwords import STOPWORDS_PATH, is_stopword, stopword_lists


def test_lists_come_from_presets_stopwords_json():
    lists = stopword_lists()
    assert set(lists) == {"es", "en"}
    assert lists == json.loads(STOPWORDS_PATH.read_text(encoding="utf-8"))
    assert STOPWORDS_PATH.parent.name == "presets"


def test_is_stopword_ignores_case_and_accents():
    assert is_stopword("Más")
    assert is_stopword("también")
    assert is_stopword("The")


def test_content_words_are_not_stopwords():
    assert not is_stopword("dormir")
    assert not is_stopword("sencillas")
    assert not is_stopword("get")  # el ejemplo del spec: "just to *get* this"
