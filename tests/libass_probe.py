"""Calibración de libass para validar font_catalog(). No forma parte del motor.

Renderiza una H y dos H en líneas separadas, con Fontsize 100, y mide en el cuadro la altura del
glifo y el paso entre líneas con bordes subpíxel. Cada fuente se renderiza con un alias de familia
único: así libass usa el archivo de assets/fonts y no una copia instalada en el sistema.
"""

import subprocess
import tempfile
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

from engine.ffbin import ffmpeg_bin
from engine.textmetrics import FONTS_DIR

WIDTH, HEIGHT = 1080, 1920
FONTSIZE = 100
WINDOW_X = (340, 740)
WINDOW_Y = (560, 1360)
TOUCH = 0.02  # cobertura mínima para contar una fila como tinta

_ASS_HEADER = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    f"PlayResX: {WIDTH}\n"
    f"PlayResY: {HEIGHT}\n"
    "WrapStyle: 2\n"
    "ScaledBorderAndShadow: yes\n"
    "\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
    "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
    "MarginL, MarginR, MarginV, Encoding\n"
)


def _ass(alias, entry, lines):
    body = "\\N".join(lines)
    if entry["italic"]:
        body = "{\\i1}" + body + "{\\i0}"
    style = (f"Style: Default,{alias},{FONTSIZE},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
             f"{-1 if entry['bold'] else 0},0,0,0,100,100,0,0,1,0,0,5,0,0,0,1")
    return (_ASS_HEADER + style + "\n\n[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            f"Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,{body}\n")


def _alias_copy(source, dest, alias):
    """Copia la fuente con la familia renombrada; conserva la subfamilia (Bold, Italic, Regular)."""
    with TTFont(source) as font:
        names = font["name"]
        subfamily = names.getDebugName(2) or "Regular"
        full = f"{alias} {subfamily}"
        postscript = f"{alias}-{subfamily}".replace(" ", "")
        for name_id in (1, 4, 6, 16, 17, 21, 22, 25):
            names.removeNames(nameID=name_id)
        for platform in ((3, 1, 0x409), (1, 0, 0)):
            names.setName(alias, 1, *platform)
            names.setName(full, 4, *platform)
            names.setName(postscript, 6, *platform)
        font.save(dest)


def _cap_em(path):
    """Altura de la H en em, según su contorno. Sirve para TTF (glyf) y OTF (CFF)."""
    with TTFont(path) as font:
        glyph_set = font.getGlyphSet()
        pen = BoundsPen(glyph_set)
        glyph_set[font.getBestCmap()[ord("H")]].draw(pen)
        _, y_min, _, y_max = pen.bounds
        return (y_max - y_min) / font["head"].unitsPerEm


def _render(ass_text, workdir):
    """Primer cuadro de libass sobre negro, en RGB crudo. Las rutas de fonts van relativas a workdir."""
    (workdir / "subtitles.ass").write_text(ass_text, encoding="utf-8")
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           f"color=c=black:s={WIDTH}x{HEIGHT}:d=1", "-vf", "ass=subtitles.ass:fontsdir=fonts",
           "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    frame = subprocess.run(cmd, cwd=workdir, capture_output=True, check=True).stdout
    if len(frame) != WIDTH * HEIGHT * 3:
        raise RuntimeError(f"cuadro de {len(frame)} bytes, se esperaban {WIDTH * HEIGHT * 3}")
    return frame


def _blocks(frame):
    """Bloques de tinta en la ventana, como (borde superior, borde inferior) con decimales.

    Cada fila vale su cobertura máxima en x (la barra de la H cubre el ancho del trazo). El borde
    superior del bloque es la fila de arriba recortada por su cobertura, y el inferior, la de abajo.
    """
    coverage = []
    for y in range(*WINDOW_Y):
        start = (y * WIDTH + WINDOW_X[0]) * 3
        end = (y * WIDTH + WINDOW_X[1]) * 3
        coverage.append(max(frame[start:end:3]) / 255)
    blocks = []
    first = None
    for index, value in enumerate(coverage + [0.0]):
        if value > TOUCH and first is None:
            first = index
        elif value <= TOUCH and first is not None:
            last = index - 1
            blocks.append((WINDOW_Y[0] + first + (1 - coverage[first]),
                           WINDOW_Y[0] + last + coverage[last]))
            first = None
    return blocks


def probe_font(index, entry):
    """Altura de H y paso entre líneas medidos en libass, frente a lo que predice font_catalog()."""
    source = FONTS_DIR / entry["file"]
    cap = _cap_em(source)
    alias = f"CalibProbe{index}"
    with tempfile.TemporaryDirectory(prefix="fontprobe-") as tmp:
        workdir = Path(tmp)
        (workdir / "fonts").mkdir()
        _alias_copy(source, workdir / "fonts" / source.name, alias)
        single = _blocks(_render(_ass(alias, entry, ["H"]), workdir))
        pair = _blocks(_render(_ass(alias, entry, ["H", "H"]), workdir))
    if len(single) != 1 or len(pair) != 2:
        raise RuntimeError(f"{entry['file']}: bloques encontrados {len(single)} y {len(pair)}, se esperaban 1 y 2")
    measured_h = single[0][1] - single[0][0]
    predicted_h = cap * FONTSIZE * entry["css_scale"]
    measured_line = (pair[1][1] - pair[0][1]) / FONTSIZE
    return {
        "file": entry["file"],
        "css_scale": entry["css_scale"],
        "h_predicted": predicted_h,
        "h_measured": measured_h,
        "err_h_pct": 100 * (measured_h - predicted_h) / predicted_h,
        "line_height": entry["line_height"],
        "line_measured": measured_line,
        "err_line_pct": 100 * (measured_line - entry["line_height"]) / entry["line_height"],
    }
