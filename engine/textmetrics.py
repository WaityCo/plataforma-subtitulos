"""Ancho real del texto en píxeles, medido con las fuentes estáticas de assets/fonts.

Sin kerning, la medida suma los avances de hmtx. Con kerning=True, la medida usa HarfBuzz (uharfbuzz),
el mismo motor de forma que libass, para que cortes y cajas coincidan con lo que se quema.
"""

from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
# Sin fuente encontrada, cada carácter mide 0.6 em. Es una aproximación, no una medida.
FALLBACK_EM = 0.6
# Métricas de respaldo si la fuente no existe: ascender 0.8 em y descender 0.2 em.
FALLBACK_METRICS = {"upem": 1000, "win_ascent": 800, "win_descent": 200, "typo_ascent": 800, "typo_descent": 200,
                    "cap_height": 700, "use_typo": False}


def _subfamily(bold, italic):
    if bold and italic:
        return "Bold Italic"
    if bold:
        return "Bold"
    if italic:
        return "Italic"
    return "Regular"


# Mismas extensiones que copia burn.fonts_for_burn: lo que se quema también se mide.
FONT_SUFFIXES = (".ttf", ".otf")


@lru_cache(maxsize=None)
def _static_files():
    """Fuentes estáticas de assets/fonts (TTF y OTF). Las variables (nombre con «[») no se usan."""
    return tuple(
        path for path in sorted(FONTS_DIR.iterdir())
        if path.is_file() and path.suffix.lower() in FONT_SUFFIXES and "[" not in path.name
    )


def _find(family, bold, italic):
    wanted = _subfamily(bold, italic)
    for path in _static_files():
        with TTFont(path) as font:
            names = font["name"]
            if names.getDebugName(1) == family and names.getDebugName(2) == wanted:
                return path
    return None


@lru_cache(maxsize=None)
def font_file(family, bold=False, italic=False):
    """TTF estático de la familia con el estilo pedido.

    Si no existe, se aproxima con otra variante de la misma familia: primero la cursiva o la recta,
    después la negrita. Sin ninguna coincidencia devuelve None. Nunca usa la variable.
    """
    options = [(bold, italic)]
    if italic:
        options.append((bold, False))
    if not bold:
        options.append((True, italic))
        if italic:
            options.append((True, False))
    for option in options:
        path = _find(family, *option)
        if path is not None:
            return path
    return None


def font_catalog():
    """Una entrada por fuente estática de assets/fonts, con las métricas que usa libass.

    css_scale: factor por el que el frontend multiplica font_size en CSS para que la altura de los
    glifos coincida con libass al mismo Fontsize. libass escala el em por usWinAscent + usWinDescent.
    line_height: paso entre líneas de libass, como múltiplo de font_size.
    file: nombre del archivo dentro de assets/fonts.
    """
    catalog = []
    for path in _static_files():
        with TTFont(path) as font:
            names, head, hhea, os2 = font["name"], font["head"], font["hhea"], font["OS/2"]
            upem = head.unitsPerEm
            win_sum = os2.usWinAscent + os2.usWinDescent
            subfamily = names.getDebugName(2) or ""
            catalog.append({
                "family": names.getDebugName(1),
                "bold": "Bold" in subfamily,
                "italic": "Italic" in subfamily,
                "file": path.name,
                "units_per_em": upem,
                "ascent": hhea.ascent,
                "descent": hhea.descent,
                "win_ascent": os2.usWinAscent,
                "win_descent": os2.usWinDescent,
                "css_scale": upem / win_sum,
                # libass ajusta el em para que la altura win (ascent + descent) mida font_size: el paso
                # entre líneas sale de esa altura, no de hhea.
                "line_height": win_sum / upem * (upem / win_sum),
            })
    return catalog


@lru_cache(maxsize=None)
def _tables(path):
    with TTFont(path) as font:
        return font.getBestCmap(), dict(font["hmtx"].metrics), font["head"].unitsPerEm


@lru_cache(maxsize=None)
def _hb_font(path):
    """Fuente de HarfBuzz para path. Se importa aquí para no cargarla si nadie mide con kerning."""
    import uharfbuzz as hb

    face = hb.Face(hb.Blob.from_file_path(str(path)))
    return hb.Font(face)


@lru_cache(maxsize=None)
def _shaped_units(path, text):
    """Avance total de text en unidades de fuente, con kerning, como lo calcula HarfBuzz."""
    import uharfbuzz as hb

    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.guess_segment_properties()
    hb.shape(_hb_font(path), buffer, {"kern": True})
    return sum(position.x_advance for position in buffer.glyph_positions)


def text_width(text, family, bold, size, italic=False, kerning=False):
    """Ancho de text en píxeles a size px: suma de avances. Con kerning, lo ajusta con HarfBuzz."""
    path = font_file(family, bold, italic)
    if path is None:
        return len(text) * FALLBACK_EM * size
    if kerning:
        return _shaped_units(path, text) * size / _tables(path)[2]
    cmap, advances, upem = _tables(path)
    units = 0
    for char in text:
        glyph = cmap.get(ord(char))
        units += advances[glyph][0] if glyph in advances else FALLBACK_EM * upem
    return units * size / upem


@lru_cache(maxsize=None)
def _vertical_metrics(path):
    with TTFont(path) as font:
        os2 = font["OS/2"]
        upem = font["head"].unitsPerEm
        cap = getattr(os2, "sCapHeight", 0) or round(upem * 0.7)
        return {
            "upem": upem,
            "win_ascent": os2.usWinAscent,
            "win_descent": os2.usWinDescent,
            "typo_ascent": os2.sTypoAscender,
            "typo_descent": -os2.sTypoDescender,
            "cap_height": cap,
            "use_typo": bool(os2.fsSelection & (1 << 7)),
        }


def css_scale(family, bold=False, italic=False):
    """Factor de font_size a px CSS: upem / (win_ascent + win_descent), igual que en font_catalog()."""
    metrics = vertical_metrics(family, bold, italic)
    return metrics["upem"] / (metrics["win_ascent"] + metrics["win_descent"])


def vertical_metrics(family, bold=False, italic=False):
    """Métricas verticales de la fuente, en unidades de fuente (upem). Sin fuente, usa FALLBACK_METRICS.

    win_ascent y win_descent son las que usa libass. typo_ascent y typo_descent son las del modelo CSS
    (con USE_TYPO_METRICS). cap_height es la altura de mayúscula.
    """
    path = font_file(family, bold, italic)
    return dict(FALLBACK_METRICS) if path is None else dict(_vertical_metrics(path))


@lru_cache(maxsize=None)
def _glyph_bearings(path, char):
    """Margen izquierdo y derecho de la tinta de char, en unidades de fuente. 0 si el glifo no tiene contorno."""
    with TTFont(path) as font:
        cmap = font.getBestCmap()
        name = cmap.get(ord(char))
        if name is None or "glyf" not in font:
            return 0, 0
        glyph = font["glyf"][name]
        advance = font["hmtx"].metrics[name][0]
        if not hasattr(glyph, "xMin"):
            return 0, 0
        return glyph.xMin, advance - glyph.xMax


def side_bearings(text, family, bold, size, italic=False):
    """Bearings de la tinta en px a size: (margen del primer glifo, margen del último) de text.

    Con el ancho de avance, la tinta de una línea empieza lsb después de su origen y acaba rsb antes de su final.
    Sin fuente devuelve (0, 0).
    """
    path = font_file(family, bold, italic)
    if path is None or not text:
        return 0.0, 0.0
    upem = _tables(path)[2]
    left, _ = _glyph_bearings(path, text[0])
    _, right = _glyph_bearings(path, text[-1])
    return left * size / upem, right * size / upem


@lru_cache(maxsize=None)
def _glyph_vertical(path, char):
    """yMax e yMin del contorno de char, en unidades de fuente. 0, 0 si el glifo no tiene contorno."""
    with TTFont(path) as font:
        name = font.getBestCmap().get(ord(char))
        if name is None or "glyf" not in font:
            return 0, 0
        glyph = font["glyf"][name]
        if not hasattr(glyph, "yMax"):
            return 0, 0
        return glyph.yMax, glyph.yMin


def vertical_bearings(text, family, bold, size, italic=False):
    """Altura de la tinta de text sobre la línea base y bajo ella, en px a size: (yMax, -yMin).

    Son los extremos reales de los contornos (incluidos los redondeles que pasan de la altura de mayúscula).
    """
    path = font_file(family, bold, italic)
    if path is None or not text:
        return 0.0, 0.0
    upem = _tables(path)[2]
    above = max(_glyph_vertical(path, char)[0] for char in text)
    below = min(_glyph_vertical(path, char)[1] for char in text)
    return above * size / upem, -below * size / upem
