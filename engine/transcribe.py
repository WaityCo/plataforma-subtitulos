"""Transcripción local con faster-whisper y normalización de tiempos por palabra."""

import re
from functools import lru_cache

MIN_WORD_MS = 80
MAX_WORD_MS = 1200


@lru_cache(maxsize=2)
def _load_model(model_size):
    # Import diferido: el resto del motor y sus pruebas no necesitan whisper.
    from faster_whisper import WhisperModel

    return WhisperModel(model_size, device="cpu", compute_type="int8")


def transcribe(wav_path, language=None, model_size="small"):
    """Devuelve [{"text", "start", "end"}] con tiempos en segundos ya normalizados."""
    model = _load_model(model_size)
    segments, _info = model.transcribe(
        str(wav_path),
        language=language,
        word_timestamps=True,
        vad_filter=True,
    )
    raw = [(word.word, word.start, word.end) for segment in segments for word in (segment.words or [])]
    return normalize_words(raw)


_NUMBER_TAIL = re.compile(r"^[.,]\d")  # ".000" o ",5": lo que sigue a un número y forma parte de él
_ENDS_IN_DIGIT = re.compile(r"\d$")
_NUMBER_SUFFIXES = ("%", "€", "$")


def merge_number_tokens(tokens):
    """Une lo que Whisper parte de un número o de una cifra con signo.

    tokens es [(texto, inicio, fin)] sin espacios. «3» y «.000» pasan a «3.000»; «50» y «%» a «50%»; «5» y «€»
    a «5€». Un «$» delante de un número se pega a él. El token resultante empieza donde empezó el primero y
    termina donde termina el último.
    """
    merged = []
    for text, start, end in tokens:
        if merged:
            previous, previous_start, _ = merged[-1]
            if _ENDS_IN_DIGIT.search(previous) and (_NUMBER_TAIL.match(text) or text in _NUMBER_SUFFIXES):
                merged[-1] = (previous + text, previous_start, end)
                continue
            if previous == "$" and text[:1].isdigit():
                merged[-1] = ("$" + text, previous_start, end)
                continue
        merged.append((text, start, end))
    return merged


def normalize_words(raw_words):
    """Fuerza entre 0.08 y 1.2 s por palabra y elimina solapes. Antes une los números que Whisper parte.

    raw_words es una secuencia de (texto, inicio, fin) en orden temporal. Se calcula en
    milisegundos enteros para que los tiempos de salida sean exactos.
    """
    tokens = [(text.strip(), start, end) for text, start, end in raw_words]
    words = []
    previous_end = 0
    for text, start, end in merge_number_tokens([token for token in tokens if token[0]]):
        start_ms = max(round(start * 1000), previous_end)
        end_ms = min(max(round(end * 1000), start_ms + MIN_WORD_MS), start_ms + MAX_WORD_MS)
        words.append({"text": text, "start": start_ms / 1000, "end": end_ms / 1000})
        previous_end = end_ms
    return words
