"""Binarios de FFmpeg y ffprobe que usa el motor.

Orden: variables de entorno FFMPEG_BIN y FFPROBE_BIN, después ffmpeg-full de Homebrew (keg-only,
con libass) y al final el ffmpeg del PATH, que es lo que hay en Docker o Linux.
"""

import os
import shutil
from pathlib import Path

FULL_DIR = Path("/opt/homebrew/opt/ffmpeg-full/bin")


def _resolve(env_name, tool):
    override = os.environ.get(env_name)
    if override:
        return override
    candidate = FULL_DIR / tool
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return shutil.which(tool) or tool


def ffmpeg_bin():
    """Ejecutable ffmpeg que usa el motor."""
    return _resolve("FFMPEG_BIN", "ffmpeg")


def ffprobe_bin():
    """Ejecutable ffprobe que usa el motor."""
    return _resolve("FFPROBE_BIN", "ffprobe")
