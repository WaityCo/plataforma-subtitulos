"""Paridad entre la geometría que predice engine.layout y lo que libass quema, preset a preset.

Para cada preset se quema un fotograma del primer segmento de un texto fijo sobre fondo negro (1080x1920, y
720x1280 en tres de ellos). Se mide la caja de píxeles de texto (luminancia >= 150) y se compara con la caja de
tinta que predice layout (bordes de los glifos reales, no de los avances).

Tolerancias: ancho ±3 %, bordes izquierdo y derecho ±2 % del ancho del video, centro vertical ±1 % de la
altura, alto ±3 % del alto predicho.

Ejecutado como script imprime la tabla de todos los presets:
    .venv/bin/python tests/test_layout_parity.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # permite ejecutarlo como script

import pytest  # noqa: E402
from PIL import Image  # noqa: E402

from engine import burn as burn_module  # noqa: E402
from engine.ass_builder import render_ass  # noqa: E402
from engine.ffbin import ffmpeg_bin  # noqa: E402
from engine.layout import build_segments  # noqa: E402
from engine.styles import list_presets, resolve  # noqa: E402

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
WORDS = [
    {"text": "HOLA", "start": 0.0, "end": 0.5},
    {"text": "HOY", "start": 0.5, "end": 1.0},
    {"text": "TE", "start": 1.0, "end": 1.5},
]
PRESETS = [preset["name"] for preset in list_presets()]
SMALL_FRAME = ("ken_remedie", "bold_karaoke", "wellness_soft")
LUMA_MIN = 150
TOLERANCE = {"width": 0.03, "edge": 0.02, "center": 0.01, "height": 0.03}


def _black_video(folder, width, height):
    path = folder / f"black_{width}x{height}.mp4"
    if not path.exists():
        subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        f"color=c=black:s={width}x{height}:r=30:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        str(path)], check=True)
    return path


def _luma(color):
    """Luminancia (Rec. 601) de un color #RRGGBB."""
    red, green, blue = (int(color[index:index + 2], 16) for index in (1, 3, 5))
    return 0.299 * red + 0.587 * green + 0.114 * blue


def _threshold(style):
    """Umbral de texto: la mitad de la luminancia del color más oscuro de texto y resaltado. Así el borde
    suave de un resaltado oscuro cuenta, y la caja azul de karaoke_box (lum. ~92) no entra."""
    return 0.5 * min(_luma(style["text_color"]), _luma(style["highlight_color"]))


def _measure(preset, width, height, folder):
    """Caja de tinta predicha por layout y caja medida en el fotograma, ambas en píxeles del video."""
    style = resolve(preset)
    segment = build_segments(WORDS, style, width, height)[0]
    scale = height / 1920
    ass = render_ass([segment], style, width, height)
    out = folder / f"{preset}_{width}x{height}.mp4"
    burn_module.burn(_black_video(folder, width, height), ass, out, FONTS)
    # Un fotograma a 0,1 s del final, dentro del tramo visible: ffmpeg toma el primer fotograma >= t.
    moment = max(0.05, segment["end"] - 0.1)
    frame = folder / f"{preset}_{width}x{height}.png"
    subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(out), "-ss", f"{moment:.3f}",
                    "-frames:v", "1", str(frame)], check=True)
    threshold = _threshold(style)
    measured = Image.open(frame).convert("L").point(lambda value: 255 if value >= threshold else 0).getbbox()
    lines = segment["layout"]["lines"]
    predicted = {  # tinta de cada línea: bordes de los glifos reales, no de los avances
        "left": min(line["ink_x"] for line in lines) * scale,
        "right": max(line["ink_x"] + line["ink_w"] for line in lines) * scale,
        "top": min(line["ink_top"] for line in lines) * scale,
        "bottom": max(line["ink_bottom"] for line in lines) * scale,
    }
    return predicted, measured


def _errors(predicted, measured, width, height):
    """Errores relativos de cada magnitud: ancho y alto sobre lo predicho, bordes y centro sobre el video."""
    left, top, right, bottom = measured
    predicted_width = predicted["right"] - predicted["left"]
    predicted_height = predicted["bottom"] - predicted["top"]
    return {
        "width": abs((right - left) - predicted_width) / predicted_width,
        "left": abs(left - predicted["left"]) / width,
        "right": abs(right - predicted["right"]) / width,
        "center": abs((top + bottom) / 2 - (predicted["top"] + predicted["bottom"]) / 2) / height,
        "height": abs((bottom - top) - predicted_height) / predicted_height,
    }


def _passes(errors):
    limits = {"width": TOLERANCE["width"], "left": TOLERANCE["edge"], "right": TOLERANCE["edge"],
              "center": TOLERANCE["center"], "height": TOLERANCE["height"]}
    return all(errors[name] <= limit for name, limit in limits.items())


@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    return tmp_path_factory.mktemp("parity")


@pytest.mark.skipif(not burn_module.is_available(), reason="sin ffmpeg con libass")
@pytest.mark.parametrize("preset", PRESETS)
def test_layout_predicts_the_burned_text_box_at_1080x1920(preset, folder):
    predicted, measured = _measure(preset, 1080, 1920, folder)
    assert measured is not None, "no se dibujó texto"
    errors = _errors(predicted, measured, 1080, 1920)
    assert _passes(errors), {name: round(value * 100, 2) for name, value in errors.items()}


@pytest.mark.skipif(not burn_module.is_available(), reason="sin ffmpeg con libass")
@pytest.mark.parametrize("preset", SMALL_FRAME)
def test_layout_predicts_the_burned_text_box_at_720x1280(preset, folder):
    predicted, measured = _measure(preset, 720, 1280, folder)
    assert measured is not None, "no se dibujó texto"
    errors = _errors(predicted, measured, 720, 1280)
    assert _passes(errors), {name: round(value * 100, 2) for name, value in errors.items()}


def table(folder):
    """Filas de la tabla de paridad: preset, resolución, caja medida, caja predicha y errores."""
    rows = []
    for width, height, names in ((1080, 1920, PRESETS), (720, 1280, SMALL_FRAME)):
        for preset in names:
            predicted, measured = _measure(preset, width, height, folder)
            errors = _errors(predicted, measured, width, height)
            rows.append((preset, f"{width}x{height}", measured, predicted, errors, _passes(errors)))
    return rows


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory(prefix="parity-") as tmp:
        print("| preset | video | medido L,T,R,B | predicho L,T,R,B | ancho % | izq % | der % | centro % | alto % | ok |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        for preset, size, measured, predicted, errors, ok in table(Path(tmp)):
            left, top, right, bottom = measured
            print(f"| {preset} | {size} | {left},{top},{right},{bottom} | "
                  f"{predicted['left']:.0f},{predicted['top']:.0f},{predicted['right']:.0f},{predicted['bottom']:.0f} | "
                  f"{errors['width'] * 100:.2f} | {errors['left'] * 100:.2f} | {errors['right'] * 100:.2f} | "
                  f"{errors['center'] * 100:.2f} | {errors['height'] * 100:.2f} | {'sí' if ok else 'no'} |")
