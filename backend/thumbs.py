"""Miniaturas exactas: un fotograma del video del usuario con los subtítulos que dibujará el quemado.

El fotograma sale con libass, igual que el render final: el mismo ASS (engine.ass_builder con el estilo
resuelto), las mismas fuentes (engine.burn.fonts_for_burn) y el mismo ffmpeg (engine.ffbin). Con -copyts,
el filtro ass ve el tiempo real del fotograma. Sin él, el fotograma queda en t=0 y el subtítulo no sale.
Así el ASS no se toca.
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .engine_bridge import FONTS_DIR

DEFAULT_WIDTH = 360
MIN_WIDTH = 16
MAX_WIDTH = 1080
THUMBS_DIR = "thumbs"  # dentro de data/jobs/<id>/
JPEG_QUALITY = 4  # escala de ffmpeg para mjpeg, donde menor es mejor. 4 ronda en torno a la calidad 85
EARLY_FRACTION = 0.6  # el instante automático sale de los segmentos que empiezan en el primer 60 % del video
END_MARGIN = 0.04  # segundos antes del final: un fotograma más allá no existe
MAX_CHARS = 24  # los caracteres de un segmento puntúan hasta este tope
SLOTS = threading.BoundedSemaphore(2)  # como mucho dos ffmpeg de miniaturas a la vez


class InvalidFrame(ValueError):
    """La petición de fotograma no es válida (por ejemplo, t fuera del video). La API responde 422."""


class FrameError(RuntimeError):
    """ffmpeg no pudo sacar el fotograma: archivo dañado o inexistente, o ffmpeg no arranca. La API responde 500."""


@dataclass(frozen=True)
class Frame:
    """Fotograma listo en disco, con su clave (ETag), el instante usado y si no tiene subtítulos."""

    path: Path
    key: str
    time: float
    empty: bool


def score(segment: dict[str, Any]) -> int:
    """Lo representativo de un segmento para el preview automático.

    Suma los caracteres del texto (hasta 24), +10 si tiene al menos dos palabras, +8 si tiene énfasis y +6 si
    tiene palabra activa o caja. Las ventanas solo existen en los modos karaoke, así que el +6 es de esos modos.
    Resta 15 si es una sola palabra.
    """
    words = [word for line in segment["lines"] for word in line]
    text = " ".join(word.get("display") or word["text"] for word in words)
    points = min(len(text), MAX_CHARS)
    if len(words) >= 2:
        points += 10
    if any(word.get("emph") for word in words):
        points += 8
    if segment.get("windows"):
        points += 6
    if len(words) == 1:
        points -= 15
    return points


def pick_time(
    segments: list[dict[str, Any]], duration: float, style: dict[str, Any], hook_end: float | None = None
) -> float:
    """Instante del preview automático: el segmento de mayor puntuación que empieza en el primer 60 % del video
    (si no hay ninguno, entre todos). En empate gana el primero. Con gancho (hook_end es su duración), prefiere
    los segmentos que empiezan después de él, para que la pastilla no tape los subtítulos; solo usa su tramo si
    no hay ninguno. Sin segmentos, la mitad del video."""
    if not segments:
        return duration / 2
    ordered = sorted(segments, key=lambda segment: segment["start"])
    candidates = [segment for segment in ordered if segment["start"] < EARLY_FRACTION * duration] or ordered
    if hook_end is not None:
        after = [segment for segment in candidates if segment["start"] >= hook_end]
        candidates = after or candidates
    best = max(candidates, key=score)  # max devuelve el primero de los empatados
    return instant_for(best, style)


def instant_for(segment: dict[str, Any], style: dict[str, Any]) -> float:
    """Instante que enseña el efecto del segmento.

    En phrase, el centro de la frase. En karaoke, caja y revelado, la tercera palabra (o la segunda, si la frase
    tiene dos): las anteriores ya están marcadas o reveladas y esa está activa o apareciendo.
    """
    words = [word for line in segment["lines"] for word in line]
    if style["mode"] == "phrase" or len(words) < 2:
        return (segment["start"] + segment["end"]) / 2
    target = words[2] if len(words) >= 3 else words[1]
    return _active_instant(target, segment)


def _active_instant(word: dict[str, Any], segment: dict[str, Any]) -> float:
    for window in segment.get("windows") or []:
        if window["index"] == word["index"]:
            return (window["start"] + window["end"]) / 2
    return (word["start"] + word["end"]) / 2


def clamp_time(time: float, duration: float) -> float:
    return min(max(time, 0.0), max(duration - END_MARGIN, 0.0))


def cache_key(
    *,
    job_id: str,
    preset: str,
    overrides: dict[str, Any] | None,
    time: float,
    width: int,
    ass_text: str | None,
    hook: dict[str, Any] | None = None,
) -> str:
    """Clave de la miniatura. Si cambian las palabras, el estilo o el gancho del fotograma, cambia la clave."""
    ass_digest = hashlib.sha256(ass_text.encode("utf-8")).hexdigest() if ass_text is not None else None
    payload = json.dumps([job_id, preset, overrides, f"{time:.3f}", width, ass_digest, hook], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def invalidate(job_folder: Path) -> None:
    """Quita las miniaturas de un job. Cuando cambian sus palabras, mostrarían el texto anterior."""
    shutil.rmtree(job_folder / THUMBS_DIR, ignore_errors=True)


def _last_line(stderr: str) -> str:
    """La última línea del error de ffmpeg, que suele ser la causa."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return lines[-1] if lines else "sin mensaje"


def _overlay_graph(has_ass: bool, overlays: list[Any], width: int) -> str:
    """Filtro del fotograma con la forma de engine.burn: el ass primero, un overlay por PNG del gancho (activo
    entre su inicio y su fin) y el escalado. Las rutas son relativas al directorio de trabajo."""
    parts = ["[0:v]ass=subtitles.ass:fontsdir=fonts[v0]" if has_ass else "[0:v]null[v0]"]
    label = "v0"
    for index, (_png, start, end, x, y) in enumerate(overlays, start=1):
        out = f"v{index}"
        parts.append(f"[{label}][{index}:v]overlay={x}:{y}:enable='between(t,{start:g},{end:g})'[{out}]")
        label = out
    parts.append(f"[{label}]scale='min({width},iw)':-2[out]")
    return ";".join(parts)


def render_frame(
    source: Path,
    ass_text: str | None,
    time: float,
    width: int,
    out: Path,
    hook: dict[str, Any] | None = None,
    video_size: tuple[int, int] | None = None,
) -> None:
    """Escribe en out el fotograma de source en el instante time, escalado a width sin agrandarlo, con los
    subtítulos de ass_text si los hay y el gancho si se pasa (video_size es el ancho y el alto del video).
    Ocupa una de las dos plazas de SLOTS mientras ffmpeg corre. Lanza InvalidFrame si el video no tiene
    fotograma en time y FrameError si ffmpeg falla."""
    from engine.burn import fonts_for_burn
    from engine.ffbin import ffmpeg_bin
    from engine.hook import render_hook

    if hook is not None and video_size is None:
        raise ValueError("Con gancho hace falta video_size: el ancho y el alto del video.")

    with SLOTS:
        workdir = Path(tempfile.mkdtemp(prefix="thumb-"))
        try:
            filters = []
            if ass_text is not None:
                (workdir / "subtitles.ass").write_text(ass_text, encoding="utf-8")
                fonts_for_burn(FONTS_DIR, workdir / "fonts")
                filters.append("ass=subtitles.ass:fontsdir=fonts")  # rutas relativas, como en burn
            overlays = render_hook(hook, *video_size, out_dir=workdir) if hook is not None else []  # PNG en workdir
            filters.append(f"scale='min({width},iw)':-2")
            partial = out.with_name(out.name + ".part")
            command = [
                ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                "-ss", f"{time:.3f}", "-copyts", "-i", str(source),
            ]
            for png, *_ in overlays:
                command += ["-loop", "1", "-i", png.name]
            if overlays:
                command += ["-filter_complex", _overlay_graph(ass_text is not None, overlays, width), "-map", "[out]"]
            else:
                command += ["-vf", ",".join(filters)]
            command += [
                "-an", "-frames:v", "1",
                "-c:v", "mjpeg", "-q:v", str(JPEG_QUALITY), "-pix_fmt", "yuvj420p",
                "-f", "image2", str(partial),
            ]
            try:
                result = subprocess.run(command, cwd=workdir, capture_output=True, text=True)
            except OSError as exc:
                raise FrameError(f"No se pudo ejecutar ffmpeg: {exc}") from exc
            if result.returncode != 0:
                partial.unlink(missing_ok=True)
                detalle = _last_line(result.stderr)
                raise FrameError(f"ffmpeg no pudo sacar el fotograma (código {result.returncode}): {detalle}")
            if not partial.is_file() or partial.stat().st_size == 0:
                # ffmpeg termina sin error pero no escribe nada: el instante no existe en el video
                partial.unlink(missing_ok=True)
                raise InvalidFrame(f"No hay fotograma en t={time:.3f} s: el video no llega a ese instante.")
            os.replace(partial, out)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
