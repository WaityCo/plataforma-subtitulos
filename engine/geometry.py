"""Geometría de un bloque en px de referencia: colocación, líneas, líneas base, palabras y cajas.

Predice lo que dibuja libass para cualquier preset: alineación 1 a 9, margin_v y margin_h escalados por la
altura, anchos con las métricas reales de la fuente (em = font_size × css_scale, kerning de HarfBuzz,
scale_x, letter_spacing y word_space_scale) y el paso entre líneas de libass (desc de una línea + asc de la
siguiente, que con una sola fuente suma font_size). Con line_height, el paso es el del modelo CSS. Las
cajas de karaoke_box siguen el modelo CSS de line-height 1 con las métricas tipográficas, más el padding.

El canvas de referencia mide 1920 de alto y, de ancho, el ancho real del video dividido por la escala de
altura. El origen es la esquina superior izquierda.
"""

from engine.grouping import italic_on, italic_scale
from engine.textmetrics import css_scale, side_bearings, text_width, vertical_bearings, vertical_metrics

REFERENCE_HEIGHT = 1920


class _Run:
    """Tramo con métricas reales: familia, negrita, cursiva, em y espaciado en px de referencia."""

    __slots__ = ("family", "bold", "italic", "em", "spacing")

    def __init__(self, family, bold, italic, em, spacing):
        self.family, self.bold, self.italic, self.em, self.spacing = family, bold, italic, em, spacing


def _runs(style):
    """Tramo normal y enfatizado con su em real (font_size × css_scale por el tamaño de emphasis_size_scale)."""
    family, bold = style["font_family"], style["font_bold"]
    base_em = style["font_size"] * css_scale(family, bold)
    base = _Run(family, bold, False, base_em, style["letter_spacing"])
    if style["emphasis_font_family"] is not None:
        emph_family, emph_bold = style["emphasis_font_family"], False
    else:
        emph_family, emph_bold = family, bold
    spacing = style["letter_spacing"] if style["emphasis_letter_spacing"] is None else style["emphasis_letter_spacing"]
    italic = style["emphasis_italic"] and italic_on(style)
    emphasis = _Run(emph_family, emph_bold, italic, base_em * style["emphasis_size_scale"], spacing)
    return base, emphasis


def _token_width(token, run, style, emphasized):
    """Ancho de un trozo de texto en px de referencia, con su compresión horizontal y su espaciado."""
    width = text_width(token, run.family, run.bold, run.em, italic=run.italic, kerning=True)
    width += run.spacing * len(token)
    compression = italic_scale(style) if (emphasized and run.italic) else style["scale_x"]
    return width * compression / 100


def _compression(style, run, emphasized):
    """Compresión horizontal de un tramo en %: la cursiva enfatizada usa scale_x_italic, lo demás scale_x."""
    return italic_scale(style) if (emphasized and run.italic) else style["scale_x"]


def _space_width(style, base):
    """Espacio entre palabras: con word_space_scale se escala solo el espacio; sin él, hereda scale_x."""
    space = text_width(" ", base.family, base.bold, base.em, kerning=True) + base.spacing
    if style["word_space_scale"] != 100:
        return space * style["word_space_scale"] / 100
    return space * style["scale_x"] / 100


def _win_extent(run):
    """Ascendente y descendente de libass para un tramo, en px de referencia."""
    metrics = vertical_metrics(run.family, run.bold, run.italic)
    return run.em * metrics["win_ascent"] / metrics["upem"], run.em * metrics["win_descent"] / metrics["upem"]


def _box_extent(run, pad_y):
    """Por encima y por debajo de la línea base de una caja de line-height 1, con su padding vertical."""
    metrics = vertical_metrics(run.family, run.bold, run.italic)
    if metrics["use_typo"]:
        ascent, descent = metrics["typo_ascent"], metrics["typo_descent"]
    else:
        ascent, descent = metrics["win_ascent"], metrics["win_descent"]
    upem = metrics["upem"]
    half_leading = (1 - (ascent + descent) / upem) / 2
    above = run.em * (ascent / upem + half_leading) + pad_y
    below = run.em * (descent / upem + half_leading) + pad_y
    return above, below


def alignment_of(style):
    """Alineación ASS efectiva: con y_pct el texto va centrado en ese punto (4 o 5), como en el ASS."""
    if style["y_pct"] is not None:
        return 5 if style["text_align"] == "center" else 4
    return style["alignment"]


def block_layout(lines, style, ref_width, boxes=False, ref_height=REFERENCE_HEIGHT):
    """Geometría de un bloque, en px de referencia.

    lines son las líneas del segmento: listas de palabras con "index", "display" y "emph". Devuelve
    {"anchor": {"x", "y", "align"}, "lines": [...]}. Cada línea trae "baseline", "ascent", "descent", "x"
    (borde izquierdo), "w" (ancho) y "words": [{"index", "x", "w"}]. Con boxes=True, cada palabra trae
    además "box": {"x", "y", "w", "h"}, la caja de karaoke_box.
    """
    base, emphasis = _runs(style)
    alignment = alignment_of(style)
    column, row = (alignment - 1) % 3, (alignment - 1) // 3  # columna 0 izquierda, 1 centro, 2 derecha; fila 0 abajo
    pad_x, pad_y = style["highlight_box_padding_x"], style["highlight_box_padding_y"]
    line_height = style["line_height"]

    measured = []
    for line in lines:
        shown = [word for word in line if word["display"]]
        runs = [emphasis if word["emph"] else base for word in shown]
        widths = [_token_width(word["display"], run, style, word["emph"]) for word, run in zip(shown, runs)]
        space = _space_width(style, base)
        extents = [_win_extent(run) for run in runs]
        above = below = 0.0
        for word, run in zip(shown, runs):
            token_above, token_below = vertical_bearings(word["display"], run.family, run.bold, run.em, run.italic)
            above, below = max(above, token_above), max(below, token_below)
        lsb = rsb = 0.0
        if shown:  # la tinta empieza en el margen del primer glifo y acaba antes del último, con su espaciado
            first, last = shown[0], shown[-1]
            first_run, last_run = runs[0], runs[-1]
            lsb = side_bearings(first["display"], first_run.family, first_run.bold, first_run.em, first_run.italic)[0]
            lsb *= _compression(style, first_run, first["emph"]) / 100
            _, rsb = side_bearings(last["display"], last_run.family, last_run.bold, last_run.em, last_run.italic)
            rsb = (rsb + last_run.spacing) * _compression(style, last_run, last["emph"]) / 100
        measured.append({
            "shown": shown, "runs": runs, "widths": widths, "space": space, "lsb": lsb, "rsb": rsb,
            "ink_above": above, "ink_below": below,
            "width": sum(widths) + space * max(0, len(widths) - 1),
            "ascent": max((a for a, _ in extents), default=_win_extent(base)[0]),
            "descent": max((d for _, d in extents), default=_win_extent(base)[1]),
            "em": max((run.em for run in runs), default=base.em),
        })

    if measured:
        if line_height is not None:
            pitches = [line_height * max(measured[k]["em"], measured[k + 1]["em"]) for k in range(len(measured) - 1)]
        else:
            pitches = [measured[k]["descent"] + measured[k + 1]["ascent"] for k in range(len(measured) - 1)]
    else:
        pitches = []

    if style["y_pct"] is not None:
        anchor_x = (style["x_pct"] if style["x_pct"] is not None else 0.5) * ref_width
        anchor_y = style["y_pct"] * ref_height
    else:
        anchor_x = {0: style["margin_h"], 1: ref_width / 2, 2: ref_width - style["margin_h"]}[column]
        anchor_y = {0: ref_height - style["margin_v"], 1: ref_height / 2, 2: style["margin_v"]}[row]
    align = ("left", "center", "right")[column] if style["y_pct"] is None else style["text_align"]

    first_ascent = measured[0]["ascent"] if measured else 0.0
    last_descent = measured[-1]["descent"] if measured else 0.0
    if row == 0:  # abajo: el descendente de la última línea queda sobre el margen inferior
        baselines = []
        cursor = anchor_y - last_descent
        for position in range(len(measured) - 1, -1, -1):
            baselines.insert(0, cursor)
            if position:
                cursor -= pitches[position - 1]
    elif row == 2:  # arriba: el ascendente de la primera línea queda bajo el margen superior
        baselines, cursor = [], anchor_y + first_ascent
        for position in range(len(measured)):
            baselines.append(cursor)
            if position < len(pitches):
                cursor += pitches[position]
    else:  # centro: el bloque se centra en el punto de anclaje
        span = sum(pitches) + last_descent - first_ascent
        baselines, cursor = [], anchor_y - span / 2
        for position in range(len(measured)):
            baselines.append(cursor)
            if position < len(pitches):
                cursor += pitches[position]

    out_lines = []
    for position, info in enumerate(measured):
        baseline = baselines[position]
        if style["y_pct"] is None:
            left = {0: anchor_x, 1: anchor_x - info["width"] / 2, 2: anchor_x - info["width"]}[column]
        else:
            left = anchor_x if align == "left" else anchor_x - info["width"] / 2
        cursor = left
        words = []
        for word, run, width in zip(info["shown"], info["runs"], info["widths"]):
            entry = {"index": word["index"], "x": cursor, "w": width}
            if boxes:
                above, below = _box_extent(run, pad_y)
                entry["box"] = {"x": cursor - pad_x, "y": baseline - above, "w": width + 2 * pad_x, "h": above + below}
            words.append(entry)
            cursor += width + info["space"]
        out_lines.append({
            "baseline": baseline, "ascent": info["ascent"], "descent": info["descent"],
            "x": left, "w": info["width"], "words": words,
            "ink_x": left + info["lsb"], "ink_w": max(0.0, info["width"] - info["lsb"] - info["rsb"]),
            "ink_top": baseline - info["ink_above"], "ink_bottom": baseline + info["ink_below"],
        })
    return {"anchor": {"x": anchor_x, "y": anchor_y, "align": align}, "lines": out_lines}
