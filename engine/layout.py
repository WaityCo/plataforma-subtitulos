"""Segmentos de subtítulo: frases, tiempos, énfasis, cortes de línea y geometría. Es la única fuente de verdad.

build_segments(words, style, width, height) devuelve los segmentos que se dibujan. El ASS
(engine.ass_builder) y el overlay del frontend usan esta misma salida y no recalculan nada.

Cada segmento es un dict:
- "start", "end": segundos. start es el inicio de su primera palabra. end es el fin de su última
  palabra más tail_s, o el inicio de la frase siguiente si el hueco es corto (blank_gap_s). Sin
  blank_gap_s, la frase sigue HOLD_SECONDS tras su última palabra sin pasar de la siguiente.
- "lines": lista de líneas. Cada línea es una lista de palabras en orden. Cada palabra es un dict:
  - "text": texto tal como está en words.json.
  - "display": texto que se dibuja, con caso y signos ya aplicados (ver styles.shown_texts). Puede ser "".
  - "start", "end": tiempos de la palabra. "reveal_at" es el mismo start: cuando aparece en reveal.
  - "emph": True si va enfatizada (cursiva, color o ambos según style["emphasis"]).
  - "index": posición de la palabra en words.
  - "family": familia con la que se dibuja (la de emphasis_font_family si la palabra va enfatizada).
  - "italic": True si la palabra va en cursiva.
  - "size_scale": escala de tamaño respecto al tramo normal (emphasis_size_scale si va enfatizada, 1.0 si no).
- "fit": porcentaje de escala. Es 100 salvo que una línea sea más ancha que el área útil.
- "windows": en karaoke, karaoke_sweep, karaoke_box y reveal. Lista de {"index", "start", "end"} con la
  ventana de cada palabra. En karaoke es el tramo de su evento; en karaoke_sweep, la duración de la
  palabra en el barrido; en karaoke_box y reveal, desde la palabra hasta la siguiente (o el fin del
  bloque), de modo que las ventanas son contiguas. En phrase es [].
- "layout": geometría del bloque en px de referencia (ver engine.geometry.block_layout): "anchor" con
  x, y y align; y por línea "baseline", "ascent", "descent", "x", "w" y las palabras con "index", "x" y "w".
- "boxes": solo en karaoke_box. Lista de {"index", "x", "y", "w", "h"}: caja de cada palabra activa.

Todas las medidas de "layout" y "boxes" son px de referencia de un canvas de 1920 de alto. Para dibujarlas
en un video de altura H, multiplica por H / 1920. El ancho de referencia es el ancho del video entre H / 1920.
"""

import math

from engine.emphasis import select_emphasis_multi
from engine.geometry import block_layout
from engine.grouping import base_run, emphasis_run, group_words, italic_flags, italic_on, layout_scale
from engine.grouping import line_measure, lines_for, with_emphasis, with_shown

# Sin blank_gap_s, la frase sigue visible este tiempo tras su última palabra, sin pasar del inicio de la siguiente.
HOLD_SECONDS = 0.3


def build_segments(words, style, width, height):
    """Segmentos de words con el estilo resuelto (styles.resolve) para un video de width x height."""
    measure, limit = line_measure(style, width, height, style["max_chars"])
    px_measure, px_limit = line_measure(style, width, height)
    groups = group_words(words, style, width, height)
    if _lexicon_on(style):
        groups = _apply_lexicon(groups, style, measure, limit)
    ref_width = width / layout_scale(height)
    segments = []
    for position, group in enumerate(groups):
        next_start = groups[position + 1]["start"] if position + 1 < len(groups) else None
        end = _segment_end(group, next_start, style)
        segments.append(_segment(group, end, style, px_measure, px_limit, ref_width))
    return segments


def segments_from_phrases(phrases, style, width, height):
    """Segmentos desde frases ya partidas, como las del gold: sin reglas de corte ni de tiempo.

    phrases es una lista de frases; cada frase es una lista de palabras {"text", "start", "end"} y
    opcionalmente "emph". Un segmento va del inicio de su primera palabra al fin de la última, y el
    énfasis sale solo de las marcas "emph" True.
    """
    px_measure, px_limit = line_measure(style, width, height)
    ref_width = width / layout_scale(height)
    segments = []
    first = 0
    for words in phrases:
        if not words:
            continue
        words = with_shown(words, style)
        emph = {index for index, word in enumerate(words) if word.get("emph") is True}
        flags = italic_flags(words, emph, style)
        lines = lines_for([(word["shown"], flag) for word, flag in zip(words, flags)], px_measure, px_limit, style)
        group = {
            "first": first,
            "start": words[0]["start"],
            "end": words[-1]["end"],
            "words": words,
            "emph": emph,
            "italic": flags,
            "lines": lines,
        }
        segments.append(_segment(group, group["end"], style, px_measure, px_limit, ref_width))
        first += len(words)
    return segments


def segments_from_blocks(blocks, style, width, height):
    """Segmentos desde bloques ya partidos, como los del gold de bloques: sin reglas de corte ni de tiempo.

    Cada bloque es {"start", "end", "words", "lines", "scale"}. words son palabras {"text", "start", "end",
    "emph"}; lines son los índices de palabra de cada línea (si falta, se parte por ancho). El segmento sale
    en el end del bloque, o sea corte seco. scale, si existe, es la escala del bloque (1.0 = tamaño normal) y
    se aplica con el mismo ajuste de fit que la escala por ancho.
    """
    px_measure, px_limit = line_measure(style, width, height)
    ref_width = width / layout_scale(height)
    segments = []
    first = 0
    for block in blocks:
        words = with_shown(block["words"], style)
        emph = {index for index, word in enumerate(words) if word.get("emph") is True}
        flags = italic_flags(words, emph, style)
        lines = block.get("lines")
        if lines is None:
            lines = lines_for([(word["shown"], flag) for word, flag in zip(words, flags)], px_measure, px_limit, style)
        group = {
            "first": first,
            "start": block["start"],
            "end": block["end"],
            "words": words,
            "emph": emph,
            "italic": flags,
            "lines": lines,
        }
        segment = _segment(group, block["end"], style, px_measure, px_limit, ref_width)
        if block.get("scale") is not None:
            segment["fit"] = round(block["scale"] * 100)
        segments.append(segment)
        first += len(words)
    return segments


def _lexicon_on(style):
    return style["emphasis_engine"] == "lexicon" and style["emphasis"] != "none" and style["emphasis_auto"]


def _lexicon_text(word):
    return "" if word.get("emph") is False else word["text"]


def _apply_lexicon(groups, style, measure, limit):
    """Marca las frases de mayor puntaje del léxico. Las frases con marca manual no se tocan."""
    manual = [any(word.get("emph") is True for word in group["words"]) for group in groups]
    phrases = [[_lexicon_text(word) for word in group["words"]] for group in groups]
    marked = [index for index, flagged in enumerate(manual) if flagged]
    chosen = select_emphasis_multi(phrases, style["emphasis_ratio"], marked=marked,
                                   max_words=style["emphasis_max_per_segment"])
    result = []
    for group, units, flagged in zip(groups, chosen, manual):
        if units and not flagged:
            group = _with_units(group, units, style, measure, limit) or group
        result.append(group)
    return result


def _with_units(group, units, style, measure, limit):
    """El grupo con todas sus unidades; si no caben en max_lines, con menos, hasta la primera. None si ninguna cabe."""
    for count in range(len(units), 0, -1):
        emph = {index for start, end in units[:count] for index in range(start, end)}
        found = with_emphasis(group, emph, style, measure, limit)
        if found is not None:
            return found
    return None


def _segment_end(group, next_start, style):
    last = group["end"]
    if style["blank_gap_s"] is None:
        end = last + HOLD_SECONDS
        if next_start is not None:
            end = min(end, next_start)
        return max(last, end)
    # Regla de animación de la referencia: un hueco corto se cubre hasta la frase siguiente, y una pausa
    # real deja la pantalla vacía tras tail_s. min_duration_s evita destellos, sin pisar la frase siguiente.
    if next_start is not None and next_start - last < style["blank_gap_s"]:
        end = next_start
    else:
        end = last + style["tail_s"]
    end = max(end, group["start"] + style["min_duration_s"])
    if next_start is not None:
        end = min(end, next_start)
    return max(last, end)


def _segment(group, end, style, px_measure, px_limit, ref_width):
    words = group["words"]
    first = group["first"]
    lines = [
        [_word(words[index], first + index, index in group["emph"], style) for index in line]
        for line in group["lines"]
    ]
    segment = {
        "start": group["start"],
        "end": end,
        "lines": lines,
        "fit": _fit(group, px_measure, px_limit),
        "windows": _windows(group, end, style),
        "layout": block_layout(lines, style, ref_width, boxes=style["mode"] == "karaoke_box"),
    }
    if style["mode"] == "karaoke_box":
        segment["boxes"] = _boxes(segment)
    return segment


def _word(word, index, emph, style):
    run = emphasis_run(style) if emph else base_run(style)
    return {
        "text": word["text"],
        "display": word["shown"],
        "start": word["start"],
        "end": word["end"],
        "emph": emph,
        "index": index,
        "reveal_at": word["start"],
        "family": run.family,
        "italic": bool(emph and italic_on(style) and run.italic),
        "size_scale": style["emphasis_size_scale"] if emph else 1.0,
    }


def _fit(group, measure, limit):
    """100, o el porcentaje que hace caber la línea más ancha en el área útil.

    Vale para cualquier línea, no solo para una palabra: con max_chars el corte cuenta caracteres y
    una línea de varias palabras puede pasar del ancho. La escala se aplica a todo el evento.
    """
    percent = 100
    for line in group["lines"]:
        width = measure([(group["words"][index]["shown"], group["italic"][index]) for index in line])
        if width > limit:
            percent = min(percent, max(1, math.floor(limit / width * 100)))
    return percent


def _windows(group, end, style):
    words = group["words"]
    first = group["first"]
    shown = [index for index, word in enumerate(words) if word["shown"]]
    mode = style["mode"]
    if mode == "karaoke_sweep":
        return [{"index": first + i, "start": words[i]["start"], "end": words[i]["end"]} for i in shown]
    if mode == "karaoke":
        spans = []
        for position, index in enumerate(shown):
            start = words[index]["start"]
            stop = words[shown[position + 1]]["start"] if position + 1 < len(shown) else end
            spans.append({"index": first + index, "start": start, "end": max(start, stop)})
        return spans
    if mode in ("karaoke_box", "reveal"):
        spans = []
        for position, index in enumerate(shown):
            start = words[index]["start"]
            stop = words[shown[position + 1]]["start"] if position + 1 < len(shown) else end
            spans.append({"index": first + index, "start": start, "end": max(start, stop)})
        return spans
    return []


def _boxes(segment):
    """Caja de cada ventana de karaoke_box, tomada de la geometría del bloque."""
    by_index = {word["index"]: word for line in segment["layout"]["lines"] for word in line["words"]}
    return [{"index": window["index"], **by_index[window["index"]]["box"]} for window in segment["windows"]]
