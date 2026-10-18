"""Formato gold de timelines (*palabra* = itálica): importa a segmentos y exporta de vuelta.

Un timeline gold es {"segments": [{"start", "end", "markup"}, ...]}. Un segmento con "text": null o sin
markup es una pausa. Dentro de un markup, " / " separa dos frases que comparten un mismo tramo de tiempo.
Los tiempos de cada palabra salen repartiendo el tramo del segmento en proporción a sus caracteres.
"""

import re

from engine.layout import segments_from_phrases
from engine.styles import resolve

KEN_PRESET = "ken_remedie"
PHRASE_SEPARATOR = "/"
_ITALIC_RUN = re.compile(r"(\*[^*]+\*)")


def gold_phrases(data):
    """Frases del timeline gold: lista de frases, cada una lista de palabras {"text", "start", "end", "emph"}."""
    phrases = []
    for segment in data["segments"]:
        markup = segment.get("markup")
        if not markup:
            continue
        pieces = _phrases_in(markup)
        if not pieces:
            continue
        start, end = float(segment["start"]), float(segment["end"])
        total = sum(len(token) for tokens in pieces for token, _ in tokens)
        cursor = start
        for position, tokens in enumerate(pieces):
            if position == len(pieces) - 1:
                phrase_end = end
            else:
                phrase_end = cursor + (end - start) * sum(len(token) for token, _ in tokens) / total
            phrases.append(_timed(tokens, cursor, phrase_end))
            cursor = phrase_end
    return phrases


def gold_blocks(data):
    """Bloques del gold de bloques (timelines/A_gold de @hua_jin123) listos para layout.segments_from_blocks.

    Cada palabra dura hasta la siguiente (la del bloque, o el fin del bloque). "line" da la línea de cada palabra
    y "scale_aprox" la escala del bloque. El énfasis sale de "italic_serif".
    """
    blocks = []
    for block in data["blocks"]:
        source = block["words"]
        words, lines = [], {}
        for index, word in enumerate(source):
            end = source[index + 1]["t"] if index + 1 < len(source) else block["end"]
            words.append({"text": word["text"], "start": float(word["t"]), "end": float(end),
                          "emph": bool(word.get("italic_serif"))})
            lines.setdefault(word.get("line", 0), []).append(index)
        blocks.append({
            "start": float(block["start"]),
            "end": float(block["end"]),
            "words": words,
            "lines": [lines[key] for key in sorted(lines)],
            "scale": float(block["scale_aprox"]) if block.get("scale_aprox") is not None else None,
        })
    return blocks


def words_from_markup(data):
    """Palabras del timeline gold en orden, con tiempos por caracteres y la marca emph de la itálica."""
    return [word for phrase in gold_phrases(data) for word in phrase]


def segments_from_markup(data, style=None, width=1080, height=1920):
    """Segmentos de render (ver engine.layout) con las frases exactas del gold.

    Sin style usa ken_remedie. No aplica reglas de corte ni de timing: el énfasis es el del markup.
    """
    style = style if style is not None else resolve(KEN_PRESET)
    return segments_from_phrases(gold_phrases(data), style, width, height)


def markup_from_segments(segments):
    """Timeline gold ({"start", "end", "markup", "text"}) a partir de segmentos. Inversa de segments_from_markup."""
    timeline = []
    for segment in segments:
        tokens = [word for line in segment["lines"] for word in line]
        pieces = []
        italic_open = False
        for word in tokens:
            emph = bool(word["emph"])
            if emph and not italic_open:
                pieces.append("*" + word["text"])
                italic_open = True
            elif not emph and italic_open:
                pieces[-1] += "*"
                pieces.append(word["text"])
                italic_open = False
            else:
                pieces.append(word["text"])
        if italic_open:
            pieces[-1] += "*"
        timeline.append({
            "start": round(segment["start"], 3),
            "end": round(segment["end"], 3),
            "markup": " ".join(pieces),
            "text": " ".join(word["text"] for word in tokens),
        })
    return timeline


def _phrases_in(markup):
    """Frases de un markup como listas de (texto, itálica). Cada "/" cierra una frase."""
    phrases, current = [], []
    for piece in _ITALIC_RUN.split(markup):
        if not piece:
            continue
        italic = len(piece) > 2 and piece[0] == "*" and piece[-1] == "*"
        body = piece[1:-1] if italic else piece
        for token in body.split():
            if token == PHRASE_SEPARATOR:
                if current:
                    phrases.append(current)
                current = []
            else:
                current.append((token, italic))
    if current:
        phrases.append(current)
    return phrases


def _timed(tokens, start, end):
    """Reparte [start, end] entre los tokens en proporción a sus caracteres."""
    total = sum(len(token) for token, _ in tokens)
    words, cursor = [], start
    for index, (token, italic) in enumerate(tokens):
        if index == len(tokens) - 1:
            stop = end
        else:
            stop = cursor + (end - start) * len(token) / total
        words.append({"text": token, "start": round(cursor, 6), "end": round(stop, 6), "emph": italic})
        cursor = stop
    return words
