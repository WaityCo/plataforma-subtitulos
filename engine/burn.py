"""Quemado de subtítulos con libass en FFmpeg, progreso, fuentes del job y overlays del gancho."""

import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from engine.audio import probe_video
from engine.ffbin import ffmpeg_bin
from engine.textmetrics import FONT_SUFFIXES

TAIL_LINES = 40
# Una línea de `ffmpeg -filters` tiene la forma " T.. ass   V->V   Render ASS subtitles ...".
_ASS_FILTER = re.compile(r"^[ \t]*[TSC.]{2,3}[ \t]+ass[ \t]", re.MULTILINE)


def _has_ass_filter(listing):
    """True si la salida de `ffmpeg -filters` lista el filtro ass."""
    return _ASS_FILTER.search(listing) is not None


_ASS_HELP = re.compile(r"^Filter ass\b", re.MULTILINE)


def _ass_help_ok(returncode, text):
    """True si `ffmpeg -h filter=ass` describe el filtro. Su código de salida es 0 también cuando no
    existe, así que el texto «Filter ass» es la comprobación que cuenta."""
    return returncode == 0 and _ASS_HELP.search(text) is not None


@lru_cache(maxsize=1)
def is_available():
    """True si el ffmpeg resuelto trae el filtro ass (libass). El resultado se guarda en caché."""
    try:
        result = subprocess.run([ffmpeg_bin(), "-hide_banner", "-h", "filter=ass"], capture_output=True, text=True)
    except FileNotFoundError:
        return False
    return _ass_help_ok(result.returncode, result.stdout)


def fonts_for_burn(fonts_dir, dest):
    """Copia a dest las fuentes estáticas de fonts_dir y devuelve sus rutas.

    Se excluyen las variables (nombre con «[»): libass elegiría su instancia por defecto, que en
    Montserrat es Thin.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for source in sorted(Path(fonts_dir).iterdir()):
        if source.is_file() and source.suffix.lower() in FONT_SUFFIXES and "[" not in source.name:
            copied.append(Path(shutil.copy2(source, dest / source.name)))
    return copied


def burn(input_video, ass_text, output_path, fonts_dir, preview_seconds=None, progress=None, overlays=()):
    """Quema ass_text sobre input_video y escribe output_path.

    overlays es una lista de (png, inicio, fin, x, y) en píxeles del video: cada PNG se superpone después
    del filtro ass mientras t está entre inicio y fin (ver engine.hook.render_hook). preview_seconds recorta
    la salida a esos segundos con un preset más rápido. progress recibe ("burn", porcentaje). Lanza
    RuntimeError con las últimas líneas de stderr si FFmpeg falla.
    """
    if not is_available():
        raise RuntimeError("El ffmpeg resuelto no tiene el filtro ass (libass). Instala ffmpeg-full.")
    report = progress or (lambda stage, percent: None)
    source = Path(input_video).resolve()
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="burn-"))
    try:
        (workdir / "subtitles.ass").write_text(ass_text, encoding="utf-8")
        fonts_for_burn(fonts_dir, workdir / "fonts")
        copied = _copy_overlays(overlays, workdir)
        total = float(preview_seconds) if preview_seconds is not None else probe_video(source)["duration"]
        _run(_command(source, output, preview_seconds, copied, total), workdir, output, total, report)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _copy_overlays(overlays, workdir):
    """Copia cada PNG a workdir con un nombre relativo (sin rutas con apóstrofes) y devuelve sus datos."""
    copied = []
    for index, (png, start, end, x, y) in enumerate(overlays):
        name = f"overlay_{index}.png"
        shutil.copy2(png, workdir / name)
        copied.append((name, float(start), float(end), int(x), int(y)))
    return copied


def _filter_graph(overlays):
    """Filtro con el ass primero y un overlay por PNG, cada uno activo en su tramo. Devuelve (grafo, salida)."""
    parts = ["[0:v]ass=subtitles.ass:fontsdir=fonts[v0]"]
    label = "v0"
    for index, (_name, start, end, x, y) in enumerate(overlays, start=1):
        out = f"v{index}"
        parts.append(f"[{label}][{index}:v]overlay={x}:{y}:enable='between(t,{start:g},{end:g})'[{out}]")
        label = out
    return ";".join(parts), label


def _command(source, output, preview_seconds, overlays=(), duration=None):
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", "-i", str(source)]
    for name, _start, _end, _x, _y in overlays:
        cmd += ["-loop", "1", "-i", name]
    if preview_seconds is not None:
        cmd += ["-t", f"{preview_seconds:g}", "-preset", "veryfast", "-crf", "23"]
    else:
        cmd += ["-preset", "medium", "-crf", "18"]
        if overlays and duration:
            # Los PNG en bucle no terminan nunca: la salida se corta con la duración del video.
            cmd += ["-t", f"{duration:g}"]
    if overlays:
        graph, label = _filter_graph(overlays)
        cmd += ["-filter_complex", graph, "-map", f"[{label}]"]
    else:
        cmd += ["-vf", "ass=subtitles.ass:fontsdir=fonts", "-map", "0:v:0"]
    cmd += [
        "-map", "0:a?",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(output),
    ]
    return cmd


def _run(cmd, workdir, output, total, report):
    report("burn", 0.0)
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errors:
        process = subprocess.Popen(cmd, cwd=workdir, stdout=subprocess.PIPE, stderr=errors, text=True)
        for line in process.stdout:
            seconds = _progress_seconds(line)
            if seconds is not None and total > 0:
                report("burn", min(100.0, seconds / total * 100))
        if process.wait() != 0:
            output.unlink(missing_ok=True)
            raise RuntimeError("FFmpeg falló al quemar los subtítulos:\n" + _tail(errors))
    report("burn", 100.0)


def _progress_seconds(line):
    """Segundos ya renderizados según una línea de -progress; None si la línea no los trae."""
    if not line.startswith("out_time_us="):
        return None
    value = line.partition("=")[2].strip()
    return int(value) / 1_000_000 if value.isdigit() else None


def _tail(errors):
    errors.seek(0)
    return "".join(errors.readlines()[-TAIL_LINES:]).strip()
