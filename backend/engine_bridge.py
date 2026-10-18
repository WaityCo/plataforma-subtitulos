"""Adaptador hacia el paquete engine/, con las firmas del spec.

Los imports son perezosos: la API arranca aunque engine/ aún no exista.
"""

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

Progress = Callable[[str, float], None]
# Carpeta de fuentes que el motor copia al quemar (la misma que usa run_job).
FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"


class EngineUnavailable(Exception):
    """Falta el paquete engine/ o uno de sus módulos. La API responde 503."""


def _module(name: str) -> Any:
    try:
        return importlib.import_module(f"engine.{name}")
    except ImportError as exc:
        raise EngineUnavailable(f"Motor no disponible: no se pudo importar engine.{name} ({exc}).") from exc


class RealEngine:
    """Llama al motor real. Tiene la misma forma que el motor falso de las pruebas."""

    def list_presets(self) -> list[dict[str, Any]]:
        # El motor llama 'name' al identificador del preset; la API lo expone como 'id'.
        return [
            {"id": p["name"], "label": p["label"], "description": p["description"], "style": p["style"]}
            for p in _module("styles").list_presets()
        ]

    def build_segments(self, words: list[dict[str, Any]], style: dict[str, Any], width: int, height: int) -> list[Any]:
        # Segmentos que dibujan el ASS y el overlay: la única fuente de verdad del motor (engine/layout.py).
        return _module("layout").build_segments(words, style, width, height)

    def font_catalog(self) -> list[Any]:
        # Catálogo de fuentes tal cual lo devuelve el motor.
        return _module("textmetrics").font_catalog()

    def resolve_style(self, preset: str, overrides: dict[str, Any] | None) -> dict[str, Any]:
        # ValueError significa estilo inválido; jobs.py lo convierte en 422.
        return _module("styles").resolve(preset, overrides)

    def build_ass(self, words: list[dict[str, Any]], style: dict[str, Any], width: int, height: int) -> str:
        return _module("ass_builder").build_ass(words, style, width, height)

    def transcribe(
        self,
        *,
        video_path: Path,
        job_dir: Path,
        preset: str,
        overrides: dict[str, Any] | None,
        language: str | None,
        model_size: str,
        progress: Progress,
    ) -> dict[str, Any]:
        # burn=False: audio, transcripción y ASS. El quemado va aparte para no transcribir dos veces.
        return _module("pipeline").run_job(
            video_path=video_path,
            job_dir=job_dir,
            preset=preset,
            overrides=overrides,
            language=language,
            model_size=model_size,
            preview_seconds=None,
            progress=progress,
            burn=False,
        )

    def burn_available(self) -> bool:
        # El motor decide si el ffmpeg resuelto trae libass (filtro ass).
        return bool(_module("burn").is_available())

    def burn(
        self,
        *,
        video_path: Path,
        ass_path: Path,
        output_path: Path,
        preview_seconds: float | None = None,
        progress: Progress | None = None,
        hook: dict[str, Any] | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        # Reutiliza el ASS ya generado: no vuelve a transcribir. El motor copia las fuentes a una
        # carpeta de trabajo, así que la ruta de fuentes puede llevar apóstrofe.
        # El gancho se dibuja con el tamaño del video del job (el mismo que el ASS), con sus PNG en la carpeta del job.
        if hook is not None and (width is None or height is None):
            raise ValueError("Con gancho hacen falta width y height del video.")
        ass_text = ass_path.read_text(encoding="utf-8")
        overlays = ()
        if hook is not None:
            overlays = _module("hook").render_hook(hook, width, height, out_dir=ass_path.parent / "hook")
        _module("burn").burn(
            video_path,
            ass_text,
            output_path,
            FONTS_DIR,
            preview_seconds=preview_seconds,
            progress=progress,
            overlays=overlays,
        )
