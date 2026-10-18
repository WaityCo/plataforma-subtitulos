"""Motor de pruebas con el motor real salvo la transcripción (whisper): estilos, ASS, segmentos, fotogramas y
quemado son reales. Lo usan las pruebas de integración y las de miniaturas."""

import subprocess

import pytest

from backend.engine_bridge import RealEngine
from backend.tests.fakes import FakeEngine

REAL = RealEngine()
requires_libass = pytest.mark.skipif(
    not REAL.burn_available(), reason="FFmpeg sin libass: engine.burn.is_available() es falso"
)


class MotorConTranscripcionFalsa(FakeEngine):
    """Motor real salvo la transcripción. Las palabras son las de self.words."""

    def list_presets(self):
        return REAL.list_presets()

    def resolve_style(self, preset, overrides):
        return REAL.resolve_style(preset, overrides)

    def build_ass(self, words, style, width, height):
        return REAL.build_ass(words, style, width, height)

    def build_segments(self, words, style, width, height):
        return REAL.build_segments(words, style, width, height)

    def burn_available(self):
        return REAL.burn_available()

    def burn(self, *, video_path, ass_path, output_path, preview_seconds=None, progress=None,
             hook=None, width=None, height=None):
        REAL.burn(
            video_path=video_path,
            ass_path=ass_path,
            output_path=output_path,
            preview_seconds=preview_seconds,
            progress=progress,
            hook=hook,
            width=width,
            height=height,
        )


def make_clip(folder, seconds=5, name="clip.mp4"):
    """Video de prueba con ffmpeg lavfi, de 720x1280 y sin audio."""
    from engine.ffbin import ffmpeg_bin

    target = folder / name
    subprocess.run(
        [
            ffmpeg_bin(), "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=720x1280:rate=25",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(target),
        ],
        check=True,
    )
    return target


def gray_pixels(path) -> bytes:
    """Luminancia de una imagen, píxel a píxel, decodificada con ffmpeg."""
    from engine.ffbin import ffmpeg_bin

    return subprocess.run(
        [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True,
        check=True,
    ).stdout


def changed_pixels(a, b) -> int:
    """Píxeles que difieren de forma apreciable (más de 40 niveles) entre dos imágenes del mismo tamaño."""
    return sum(1 for x, y in zip(gray_pixels(a), gray_pixels(b)) if abs(x - y) > 40)
