"""Transcripción local y normalización de tiempos por palabra.

Motor por defecto: faster-whisper con BatchedInferencePipeline, 4 hilos de CPU y beam 1. En el benchmark de P1 fue
unas nueve veces más rápido que el modo anterior (60 s de inglés), con el mismo WER y la misma F1 de segmentación.
mlx-whisper (Metal) es opcional: SUBS_ASR_ENGINE=mlx. SUBS_ASR_MODEL es el modelo de un job que no pide otro.
"""

import os
import re
import threading
import wave
from functools import lru_cache

MIN_WORD_MS = 80
MAX_WORD_MS = 1200

ENGINES = ("faster-whisper", "mlx")
DEFAULT_ENGINE = "faster-whisper"
DEFAULT_MODEL = "small"
# En este Mac, 4 hilos (los de rendimiento) fueron más rápidos que 8 en el benchmark de P1.
CPU_THREADS = 4
BATCH_SIZE = 8
# Repositorios de mlx-community por tamaño. Un valor con "/" se usa como repositorio tal cual.
MLX_MODELS = {
    "tiny": "mlx-community/whisper-tiny-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large-v2": "mlx-community/whisper-large-v2-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
}
# Una transcripción a la vez: el worker y el precalentamiento comparten el mismo modelo.
_LOCK = threading.RLock()


def configured_engine():
    """Motor de SUBS_ASR_ENGINE, o el de por defecto. Un valor no admitido lanza ValueError."""
    value = os.environ.get("SUBS_ASR_ENGINE", "").strip() or DEFAULT_ENGINE
    if value not in ENGINES:
        raise ValueError(f"SUBS_ASR_ENGINE no admitido: {value!r}. Usa uno de: {', '.join(ENGINES)}.")
    return value


def default_model():
    """Modelo de un job que no pide otro: SUBS_ASR_MODEL, o small."""
    return os.environ.get("SUBS_ASR_MODEL", "").strip() or DEFAULT_MODEL


@lru_cache(maxsize=2)
def _load_model(model_size):
    # Import diferido: el resto del motor y sus pruebas no necesitan whisper.
    from faster_whisper import BatchedInferencePipeline, WhisperModel

    model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=CPU_THREADS)
    return BatchedInferencePipeline(model=model)


def _faster_whisper_size(model_size):
    if "/" in model_size:
        raise ValueError(
            f"SUBS_ASR_MODEL {model_size!r} es un repositorio de mlx. Con faster-whisper usa un tamaño, como small."
        )
    return model_size


def _faster_whisper_raw(model_size, wav_path, language):
    pipeline = _load_model(_faster_whisper_size(model_size))
    segments, _info = pipeline.transcribe(
        str(wav_path),
        language=language,
        word_timestamps=True,
        vad_filter=True,
        beam_size=1,
        batch_size=BATCH_SIZE,
    )
    return [(word.word, word.start, word.end) for segment in segments for word in (segment.words or [])]


def _import_mlx():
    # Import diferido: mlx solo existe en Apple Silicon.
    try:
        import mlx_whisper
    except ImportError as exc:
        raise RuntimeError("SUBS_ASR_ENGINE=mlx necesita mlx-whisper (solo Apple Silicon): pip install mlx-whisper.") from exc
    return mlx_whisper


def _mlx_repo(model_size):
    if "/" in model_size:
        return model_size
    if model_size not in MLX_MODELS:
        raise ValueError(
            f"Modelo mlx no admitido: {model_size!r}. Usa uno de: {', '.join(MLX_MODELS)}, o un repositorio de Hugging Face."
        )
    return MLX_MODELS[model_size]


def _read_pcm16_wav(wav_path):
    """Muestras float32 de un WAV mono de 16 kHz y 16 bits, el formato que escribe engine.audio.extract_audio."""
    import numpy as np

    with wave.open(str(wav_path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getframerate() != 16000 or wav.getsampwidth() != 2:
            raise ValueError("Se espera un WAV mono de 16 kHz con muestras de 16 bits.")
        frames = wav.readframes(wav.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def _mlx_raw(model_size, wav_path, language):
    result = _import_mlx().transcribe(
        _read_pcm16_wav(wav_path),
        path_or_hf_repo=_mlx_repo(model_size),
        language=language,
        word_timestamps=True,
    )
    return [
        (word["word"], word["start"], word["end"])
        for segment in result.get("segments", [])
        for word in segment.get("words") or []
    ]


def transcribe(wav_path, language=None, model_size=None):
    """Devuelve [{"text", "start", "end"}] con tiempos en segundos ya normalizados."""
    engine = configured_engine()
    model = model_size or default_model()
    with _LOCK:
        if engine == "mlx":
            raw = _mlx_raw(model, wav_path, language)
        else:
            raw = _faster_whisper_raw(model, wav_path, language)
    return normalize_words(raw)


def warmup(model_size=None):
    """Carga el modelo y lo calienta con un segundo de silencio, sin guardar nada. Devuelve None.

    El backend lo llama al arrancar, en un hilo, para que el primer job no pague la carga. Si el motor no está
    disponible, lanza la excepción y el backend la registra.
    """
    import numpy as np

    engine = configured_engine()
    model = model_size or default_model()
    silence = np.zeros(16000, dtype=np.float32)
    with _LOCK:
        if engine == "mlx":
            _import_mlx().transcribe(silence, path_or_hf_repo=_mlx_repo(model), word_timestamps=True)
        else:
            segments, _info = _load_model(_faster_whisper_size(model)).transcribe(
                silence, word_timestamps=True, vad_filter=False, beam_size=1, batch_size=BATCH_SIZE
            )
            list(segments)


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
