"""Validación de la subida y metadatos del video con ffprobe."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Extensión admitida -> content-type que debe venir con ella.
UPLOAD_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}


class InvalidVideo(Exception):
    """El archivo no es un video admitido. La API responde 400."""


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    duration: float


# Content-types que mandan curl y otros clientes cuando no conocen el tipo: con ellos, el contenido decide (ffprobe).
GENERIC_CONTENT_TYPES = ("application/octet-stream", "")


def validate_upload(filename: str, content_type: str) -> str:
    """Devuelve la extensión validada. El nombre que envía el usuario nunca se usa como ruta."""
    ext = Path(filename).suffix.lower()
    if ext not in UPLOAD_TYPES:
        raise InvalidVideo("Formato no admitido: usa mp4, mov o webm.")
    declared = content_type.split(";")[0].strip().lower()
    if declared != UPLOAD_TYPES[ext] and declared not in GENERIC_CONTENT_TYPES:
        raise InvalidVideo(f"El content-type '{declared}' no corresponde a {ext}.")
    return ext


def probe_video(path: Path) -> VideoInfo:
    """Lee ancho, alto y duración con el ffprobe del motor. Si el video está rotado, intercambia ancho y alto."""
    try:
        proc = subprocess.run(
            [_ffprobe(), "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise InvalidVideo("ffprobe tardó demasiado en leer el archivo.") from exc
    if proc.returncode != 0:
        raise InvalidVideo("El archivo no es un video válido.")

    data = json.loads(proc.stdout or "{}")
    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if stream is None:
        raise InvalidVideo("El archivo no tiene pista de video.")

    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise InvalidVideo("No se pudo leer el tamaño del video.")
    # Los móviles guardan la orientación como rotación: el cuadro visible tiene ancho y alto cambiados.
    if _rotation(stream) % 180 == 90:
        width, height = height, width

    duration = _as_float(data.get("format", {}).get("duration")) or _as_float(stream.get("duration"))
    if duration <= 0:
        raise InvalidVideo("No se pudo leer la duración del video.")
    return VideoInfo(width=width, height=height, duration=round(duration, 3))


def _ffprobe() -> str:
    # El mismo ffprobe que usa el motor (ffmpeg-full si está instalado).
    from engine.ffbin import ffprobe_bin

    return ffprobe_bin()


def _rotation(stream: dict[str, Any]) -> int:
    # ffprobe la expone en side_data (versiones nuevas) o en el tag rotate (versiones antiguas).
    for side in stream.get("side_data_list", []):
        if "rotation" in side:
            return int(side["rotation"])
    return int(stream.get("tags", {}).get("rotate", 0))


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
