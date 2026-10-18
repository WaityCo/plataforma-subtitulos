"""Genera las instancias estáticas que usa libass: Montserrat Bold y ExtraBold, Montserrat Medium e Inter SemiBold.

Cada instancia sale de una fuente variable que se conserva para el frontend. Los nombres siguen el
esquema legacy que busca libass: Bold es familia "Montserrat" con subfamilia "Bold"; ExtraBold, Medium
y SemiBold usan familias propias ("Montserrat ExtraBold", "Montserrat Medium", "Inter SemiBold") con
subfamilia "Regular".

Uso: .venv/bin/python -m engine.static_fonts
"""

import io

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

from engine.textmetrics import FONTS_DIR

MONTSERRAT = FONTS_DIR / "Montserrat[wght].ttf"
INTER = FONTS_DIR / "Inter[opsz,wght].ttf"
FSSELECTION_BOLD = 1 << 5
FSSELECTION_REGULAR = 1 << 6
# Nombres tipográficos (16, 17) y variables (25) no aplican a una instancia estática legacy.
_DROP_NAMES = (16, 17, 25)

# fuente variable, ejes, archivo, familia, subfamilia, nombre completo, PostScript
INSTANCES = (
    (MONTSERRAT, {"wght": 700}, "Montserrat-Bold.ttf", "Montserrat", "Bold", "Montserrat Bold", "Montserrat-Bold"),
    (MONTSERRAT, {"wght": 800}, "Montserrat-ExtraBold.ttf", "Montserrat ExtraBold", "Regular",
     "Montserrat ExtraBold", "Montserrat-ExtraBold"),
    (MONTSERRAT, {"wght": 500}, "Montserrat-Medium.ttf", "Montserrat Medium", "Regular",
     "Montserrat Medium", "Montserrat-Medium"),
    (INTER, {"wght": 600, "opsz": 14}, "Inter-SemiBold.ttf", "Inter SemiBold", "Regular",
     "Inter SemiBold", "Inter-SemiBold"),
)


def _set_name(names, name_id, value):
    names.removeNames(nameID=name_id)
    names.setName(value, name_id, 3, 1, 0x409)
    names.setName(value, name_id, 1, 0, 0)


def build_static(source, axes, filename, family, subfamily, full, postscript, destination=FONTS_DIR):
    out = destination / filename
    instancer.main([str(source), *(f"{axis}={value}" for axis, value in axes.items()), "-o", str(out)])
    bold = subfamily == "Bold"
    with TTFont(io.BytesIO(out.read_bytes())) as font:
        names = font["name"]
        for name_id in _DROP_NAMES:
            names.removeNames(nameID=name_id)
        _set_name(names, 1, family)
        _set_name(names, 2, subfamily)
        _set_name(names, 3, f"{postscript};static")
        _set_name(names, 4, full)
        _set_name(names, 6, postscript)
        os2 = font["OS/2"]
        os2.usWeightClass = axes["wght"]
        flags = os2.fsSelection & ~(FSSELECTION_BOLD | FSSELECTION_REGULAR)
        os2.fsSelection = flags | (FSSELECTION_BOLD if bold else FSSELECTION_REGULAR)
        font["head"].macStyle = 1 if bold else 0
        buffer = io.BytesIO()
        font.save(buffer)
    out.write_bytes(buffer.getvalue())


def main():
    for spec in INSTANCES:
        build_static(*spec)
        print(f"generado {spec[2]}")


if __name__ == "__main__":
    main()
