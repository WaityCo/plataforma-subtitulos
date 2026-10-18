"""Motor falso con la misma forma que RealEngine. Sustituye whisper (transcripción) y libass (quemado)."""

import json
import threading
from typing import Any

from backend.media import probe_video

BASE_STYLE = {"font_family": "Montserrat", "font_bold": True, "font_size": 86, "mode": "karaoke", "alignment": 2}
PRESETS = {
    "ken_classic": {"font_size": 86, "mode": "karaoke"},
    "phrase_box": {"font_size": 64, "mode": "phrase"},
}


class FakeEngine:
    def __init__(self) -> None:
        self.transcriptions = 0
        self.model_sizes: list[str] = []  # model_size de cada transcripción
        self.words: list[dict[str, Any]] = [
            {"text": "hola", "start": 0.0, "end": 0.5},
            {"text": "mundo", "start": 0.5, "end": 1.0},
        ]  # lo que devuelve la transcripción falsa; se puede cambiar antes de subir un video
        self.segment_calls: list[dict[str, Any]] = []  # estilo y tamaño de cada build_segments
        self.burn_ok = False  # por defecto, como el FFmpeg actual: sin libass
        self.burn_calls: list[float | None] = []  # preview_seconds de cada quemado
        self.burn_hooks: list[dict[str, Any] | None] = []  # gancho de cada quemado
        self.gate = threading.Event()  # si está cerrado, la transcripción espera aquí
        self.gate.set()
        self.burn_gate = threading.Event()  # si está cerrado, el quemado espera aquí
        self.burn_gate.set()

    def list_presets(self) -> list[dict[str, Any]]:
        return [
            {"id": pid, "label": pid, "description": "motor falso", "style": {**BASE_STYLE, **over}}
            for pid, over in PRESETS.items()
        ]

    def resolve_style(self, preset: str, overrides: dict[str, Any] | None) -> dict[str, Any]:
        if preset not in PRESETS:
            raise ValueError(f"Preset desconocido: {preset}")
        style = {**BASE_STYLE, **PRESETS[preset], **(overrides or {})}
        if not isinstance(style["font_size"], (int, float)) or style["font_size"] <= 0:
            raise ValueError("font_size debe ser mayor que 0")
        return style

    def build_ass(self, words, style, width, height) -> str:
        lines = [f"PlayResX: {width}", f"PlayResY: {height}", f"FontSize: {style['font_size']}"]
        lines += [f"Dialogue: {word['text']}" for word in words]
        return "\n".join(lines) + "\n"

    def build_segments(self, words, style, width, height) -> list[dict[str, Any]]:
        self.segment_calls.append({"style": style, "width": width, "height": height})
        return [
            {
                "start": word["start"],
                "end": word["end"],
                "lines": [[{"text": word["text"], "display": word["text"], "start": word["start"],
                            "end": word["end"], "emph": word.get("emph") is True, "index": index}]],
                "fit": 100,
                "windows": [],
            }
            for index, word in enumerate(words)
        ]

    def transcribe(self, *, video_path, job_dir, preset, overrides, language, model_size, progress) -> dict:
        self.transcriptions += 1
        self.model_sizes.append(model_size)
        info = probe_video(video_path)
        progress("audio", 100.0)
        progress("transcribe", 42.0)
        self.gate.wait(timeout=30)
        words = [dict(word) for word in self.words]
        (job_dir / "words.json").write_text(json.dumps(words), encoding="utf-8")
        style = self.resolve_style(preset, overrides)
        (job_dir / "subtitles.ass").write_text(self.build_ass(words, style, info.width, info.height), encoding="utf-8")
        progress("subtitles", 100.0)
        return {}

    def font_catalog(self) -> list[dict[str, Any]]:
        return [{"family": "Anton", "file": "Anton-Regular.ttf"}, {"family": "Poppins", "file": "Poppins-Medium.ttf"}]

    def burn_available(self) -> bool:
        return self.burn_ok

    def burn(self, *, video_path, ass_path, output_path, preview_seconds=None, progress=None,
             hook=None, width=None, height=None) -> None:
        if not self.burn_ok:
            raise RuntimeError("El ffmpeg resuelto no tiene el filtro ass (libass).")
        self.burn_calls.append(preview_seconds)
        self.burn_hooks.append(hook)
        report = progress or (lambda stage, percent: None)
        report("burn", 50.0)
        self.burn_gate.wait(timeout=30)
        output_path.write_bytes(b"fake-preview" if preview_seconds is not None else b"fake-mp4")
        report("burn", 100.0)
