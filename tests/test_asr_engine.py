import sys
import types
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from engine import transcribe as asr


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("SUBS_ASR_ENGINE", raising=False)
    monkeypatch.delenv("SUBS_ASR_MODEL", raising=False)


def write_wav(path, channels=1, frames=16000):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * frames * channels)
    return path


class FakePipeline:
    """Imita BatchedInferencePipeline: devuelve dos palabras y guarda los argumentos de cada llamada."""

    def __init__(self):
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append((audio, kwargs))
        words = [SimpleNamespace(word=" Hola", start=0.0, end=0.5), SimpleNamespace(word=" mundo", start=0.5, end=1.0)]
        return iter([SimpleNamespace(words=words)]), None


def fake_mlx(monkeypatch, result):
    calls = []

    def transcribe(audio, **kwargs):
        calls.append((audio, kwargs))
        return result

    module = types.ModuleType("mlx_whisper")
    module.transcribe = transcribe
    monkeypatch.setitem(sys.modules, "mlx_whisper", module)
    return calls


WORDS = [{"text": "Hola", "start": 0.0, "end": 0.5}, {"text": "mundo", "start": 0.5, "end": 1.0}]


def test_default_engine_is_faster_whisper():
    assert asr.configured_engine() == "faster-whisper"


def test_engine_can_be_set_to_mlx_with_env(monkeypatch):
    monkeypatch.setenv("SUBS_ASR_ENGINE", " mlx ")
    assert asr.configured_engine() == "mlx"


def test_invalid_engine_names_the_variable(monkeypatch):
    monkeypatch.setenv("SUBS_ASR_ENGINE", "whisper-cpp")
    with pytest.raises(ValueError, match="SUBS_ASR_ENGINE"):
        asr.configured_engine()


def test_default_model_is_small_and_env_overrides_it(monkeypatch):
    assert asr.default_model() == "small"
    monkeypatch.setenv("SUBS_ASR_MODEL", "large-v3-turbo")
    assert asr.default_model() == "large-v3-turbo"


def test_mlx_maps_sizes_and_accepts_repository_ids():
    assert asr._mlx_repo("small") == "mlx-community/whisper-small-mlx"
    assert asr._mlx_repo("mlx-community/whisper-tiny-mlx") == "mlx-community/whisper-tiny-mlx"
    with pytest.raises(ValueError, match="Modelo mlx no admitido"):
        asr._mlx_repo("gigante")


def test_faster_whisper_rejects_a_repository_id():
    with pytest.raises(ValueError, match="repositorio de mlx"):
        asr._faster_whisper_size("mlx-community/whisper-small-mlx")


def test_faster_whisper_path_keeps_the_word_format_and_settings(monkeypatch, tmp_path):
    pipeline = FakePipeline()
    monkeypatch.setattr(asr, "_load_model", lambda size: pipeline)
    assert asr.transcribe(write_wav(tmp_path / "a.wav"), language="es") == WORDS
    _audio, kwargs = pipeline.calls[0]
    assert kwargs == {"language": "es", "word_timestamps": True, "vad_filter": True, "beam_size": 1, "batch_size": 8}


def test_mlx_path_reads_pcm_and_keeps_the_word_format(monkeypatch, tmp_path):
    monkeypatch.setenv("SUBS_ASR_ENGINE", "mlx")
    result = {"segments": [{"words": [{"word": " Hola", "start": 0.0, "end": 0.5},
                                      {"word": " mundo", "start": 0.5, "end": 1.0}]}]}
    calls = fake_mlx(monkeypatch, result)
    assert asr.transcribe(write_wav(tmp_path / "a.wav", frames=32000)) == WORDS
    audio, kwargs = calls[0]
    assert audio.dtype == np.float32 and audio.shape == (32000,)
    assert kwargs["path_or_hf_repo"] == "mlx-community/whisper-small-mlx"
    assert kwargs["word_timestamps"] is True


def test_mlx_missing_package_gives_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setenv("SUBS_ASR_ENGINE", "mlx")
    monkeypatch.setitem(sys.modules, "mlx_whisper", None)  # un None en sys.modules hace que el import falle
    with pytest.raises(RuntimeError, match="mlx-whisper"):
        asr.transcribe(write_wav(tmp_path / "a.wav"))


def test_pcm_reader_rejects_stereo(tmp_path):
    with pytest.raises(ValueError, match="mono"):
        asr._read_pcm16_wav(write_wav(tmp_path / "stereo.wav", channels=2))


def test_warmup_loads_the_default_model_and_runs_one_second_of_silence(monkeypatch):
    pipeline = FakePipeline()
    sizes = []
    monkeypatch.setattr(asr, "_load_model", lambda size: sizes.append(size) or pipeline)
    assert asr.warmup() is None
    assert sizes == ["small"]
    audio, kwargs = pipeline.calls[0]
    assert audio.shape == (16000,) and not audio.any()
    assert kwargs["vad_filter"] is False


def test_warmup_runs_mlx_with_the_requested_size(monkeypatch):
    monkeypatch.setenv("SUBS_ASR_ENGINE", "mlx")
    calls = fake_mlx(monkeypatch, {"segments": []})
    asr.warmup("large-v3-turbo")
    audio, kwargs = calls[0]
    assert kwargs["path_or_hf_repo"] == "mlx-community/whisper-large-v3-turbo"
    assert audio.shape == (16000,)
