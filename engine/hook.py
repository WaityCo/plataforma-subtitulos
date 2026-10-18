"""Gancho titular (estilo D de @hua_jin123): píldora blanca con el titular, kicker y rótulo de noticiero.

render_hook(spec, width, height) dibuja cada elemento como PNG con Pillow y devuelve
[(png, start, end, x, y), ...] en píxeles del video. Su atributo warnings lista los grafemas que ninguna
fuente dibuja: se omiten y se anotan. burn() los superpone con overlay=enable='between(t,start,end)'
después del filtro ass. Las medidas de referencia son de un canvas de 1080 de ancho; se escalan por
width / 1080.

spec = {"headline": str, "kicker": str opcional, "news_title": str opcional,
        "news_subtitle": str opcional, "duration_s": número de 0.5 a 10}
"""

import tempfile
import unicodedata
from functools import lru_cache
from pathlib import Path

import regex
import uharfbuzz as hb
from PIL import Image, ImageDraw, ImageFont, features

from engine.textmetrics import FONTS_DIR, _hb_font

EMOJI_FONTS = (
    ("/System/Library/Fonts/Apple Color Emoji.ttc", 160),
    ("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", 109),
    ("/usr/share/fonts/noto/NotoColorEmoji.ttf", 109),
)
# RAQM une banderas y secuencias ZWJ en un solo glifo. Con BASIC esos grafemas no se dibujan.
LAYOUT = ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC
GRAPHEME = regex.compile(r"\X")
# Un grafema con selector FE0F, ZWJ, marca de teclado, indicador regional o emoji de presentación por
# defecto va primero con la fuente de emoji. El resto va primero con la fuente de texto.
EMOJI_PRESENTATION = regex.compile(r"[‍⃣️\U0001F1E6-\U0001F1FF]|\p{Emoji_Presentation}")
REFERENCE_WIDTH = 1080
PILL_WIDTH_PCT = 0.87
PILL_RADIUS = 20
PILL_TOP_PCT = 0.43
HEADLINE_PX = 59
KICKER_GAP = 22
RED, BLUE = "#D7191C", "#1E63E9"
NEWS_TILT_DEG = 3  # PIL gira en sentido antihorario: +3 deja el borde derecho más alto, como rotate(-3deg) de CSS.
MEDIUM = "Montserrat-Medium.ttf"
BOLD = "Montserrat-Bold.ttf"


class HookElements(list):
    """Elementos de render_hook. warnings lista los grafemas omitidos porque ninguna fuente los dibuja."""

    def __init__(self, elements, warnings):
        super().__init__(elements)
        self.warnings = list(warnings)


def validate_spec(spec):
    """Comprueba el titular y la duración. Lanza ValueError con el campo que falla."""
    if not isinstance(spec, dict):
        raise ValueError("hook debe ser un objeto con headline y duration_s")
    headline = spec.get("headline")
    if not isinstance(headline, str) or not headline.strip():
        raise ValueError("hook.headline es obligatorio y no puede estar vacío")
    duration = spec.get("duration_s")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0.5 <= duration <= 10:
        raise ValueError("hook.duration_s debe ser un número entre 0.5 y 10")
    for key in ("kicker", "news_title", "news_subtitle"):
        if spec.get(key) is not None and not isinstance(spec[key], str):
            raise ValueError(f"hook.{key} debe ser texto o null")


def render_hook(spec, width, height, out_dir=None):
    """PNG de cada elemento del gancho y su posición: [(png, start, end, x, y)] en píxeles del video.

    out_dir es donde se escriben los PNG. Sin out_dir se crea una carpeta temporal que el llamador
    debe borrar; burn() copia los PNG a su propio directorio de trabajo. El resultado trae .warnings.
    """
    validate_spec(spec)
    scale = width / REFERENCE_WIDTH
    folder = Path(out_dir) if out_dir is not None else Path(tempfile.mkdtemp(prefix="hook-"))
    folder.mkdir(parents=True, exist_ok=True)
    duration = float(spec["duration_s"])
    warnings = []
    pill_width = round(width * PILL_WIDTH_PCT)
    pill_image = _pill(spec["headline"], pill_width, scale, warnings)
    pill_left = round((width - pill_width) / 2)
    pill_y = round(height * PILL_TOP_PCT)
    elements = []
    pill_path = folder / "hook_pill.png"
    pill_image.save(pill_path)
    elements.append((pill_path, 0.0, duration, pill_left, pill_y))
    if spec.get("kicker"):
        kicker_image = _kicker(spec["kicker"], pill_width, scale, warnings)
        kicker_path = folder / "hook_kicker.png"
        kicker_image.save(kicker_path)
        kicker_x = pill_left + (pill_width - kicker_image.width) // 2
        kicker_y = pill_y - kicker_image.height - round(KICKER_GAP * scale)
        elements.append((kicker_path, 0.0, duration, kicker_x, kicker_y))
    if spec.get("news_title"):
        news_image = _news_bar(spec["news_title"], RED, scale, bold=True, tilt=NEWS_TILT_DEG, warnings=warnings)
        news_path = folder / "hook_news_title.png"
        news_image.save(news_path)
        elements.append((news_path, 0.0, duration, round(width * 0.01), round(height * 0.855)))
    if spec.get("news_subtitle"):
        subtitle_image = _news_bar(spec["news_subtitle"], BLUE, scale, bold=False, tilt=0, warnings=warnings)
        subtitle_path = folder / "hook_news_subtitle.png"
        subtitle_image.save(subtitle_path)
        elements.append((subtitle_path, 0.0, duration, round(width * 0.13), round(height * 0.9)))
    return HookElements(elements, warnings)


def _font(name, px):
    return ImageFont.truetype(str(FONTS_DIR / name), max(1, round(px)), layout_engine=LAYOUT)


@lru_cache(maxsize=1)
def _emoji_font():
    """Fuente de emoji a color con su tamaño nativo: Apple Color Emoji en macOS o Noto Color Emoji en Linux."""
    for path, native in EMOJI_FONTS:
        if Path(path).is_file():
            return ImageFont.truetype(path, native, layout_engine=LAYOUT), native
    return None


def _clusters(text):
    """Grafemas en NFC y con espacios simples: 'a' + acento es una sola 'á' y una bandera es un grafema."""
    return GRAPHEME.findall(" ".join(unicodedata.normalize("NFC", text).split()))


def _covers(path, cluster):
    """True si la fuente dibuja el grafema entero. HarfBuzz marca con gid 0 el glifo que falta."""
    buffer = hb.Buffer()
    buffer.add_str(cluster)
    buffer.guess_segment_properties()
    hb.shape(_hb_font(path), buffer, {})
    ids = [info.codepoint for info in buffer.glyph_infos]
    return bool(ids) and 0 not in ids


def _emoji_covers(cluster):
    font = _emoji_font()
    return font is not None and _covers(font[0].path, cluster)


def _cluster_kind(cluster, name):
    """'emoji' o 'text' según la fuente que dibuje el grafema, o None si ninguna lo dibuja."""
    text_ok = _covers(str(FONTS_DIR / name), cluster)
    emoji_ok = _emoji_covers(cluster)
    if EMOJI_PRESENTATION.search(cluster):
        order = (("emoji", emoji_ok), ("text", text_ok))
    else:
        order = (("text", text_ok), ("emoji", emoji_ok))
    return next((kind for kind, ok in order if ok), None)


def _pieces(text, name, warnings):
    """Trozos de un texto: runs de texto con la fuente name y un trozo por cada emoji.

    Un grafema que ninguna fuente dibuja se omite y se anota en warnings, sin repetir el aviso.
    """
    pieces = []
    for cluster in _clusters(text):
        kind = _cluster_kind(cluster, name)
        if kind is None:
            message = "Sin glifo en ninguna fuente, omitido: " + " ".join(f"U+{ord(char):04X}" for char in cluster)
            if message not in warnings:
                warnings.append(message)
        elif kind == "text" and pieces and pieces[-1][0] == "text":
            pieces[-1] = ("text", pieces[-1][1] + cluster)
        else:
            pieces.append((kind, cluster))
    return pieces


def _line_metrics(font):
    ascent, descent = font.getmetrics()
    return ascent, descent


def _box_height(font):
    """Alto de la caja de línea (ascendente más descendente). A esa altura se escala cada emoji."""
    ascent, descent = _line_metrics(font)
    return ascent + descent


def _piece_width(piece, font, height):
    kind, text = piece
    if kind == "emoji":
        image = _emoji_image(text, height)
        return image.width if image is not None else 0
    return font.getlength(text)


def _line_width(line, font):
    """Ancho de una línea de palabras con un espacio entre cada dos palabras."""
    height = _box_height(font)
    width = sum(_piece_width(piece, font, height) for pieces in line for piece in pieces)
    return width + font.getlength(" ") * (len(line) - 1)


def _wrap(text, name, font, max_width, warnings):
    """Líneas de palabras (cada palabra es su lista de trozos) que caben en max_width."""
    height = _box_height(font)
    space = font.getlength(" ")
    lines, current, current_width = [], [], 0.0
    for word in text.split():
        pieces = _pieces(word, name, warnings)
        if not pieces:
            continue
        width = sum(_piece_width(piece, font, height) for piece in pieces)
        extra = space if current else 0
        if current and current_width + extra + width > max_width:
            lines.append(current)
            current, current_width = [], 0.0
            extra = 0
        current.append(pieces)
        current_width += extra + width
    if current:
        lines.append(current)
    return lines


@lru_cache(maxsize=512)
def _emoji_image(cluster, height):
    """Emoji a color recortado a su trazo y escalado a height píxeles de alto. None si no tiene trazo visible."""
    font, native = _emoji_font()
    canvas = Image.new("RGBA", (native * 2, native * 2), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text((native // 2, native // 2), cluster, font=font, embedded_color=True)
    box = canvas.getbbox()
    if box is None:
        return None
    glyph = canvas.crop(box)
    width = max(1, round(glyph.width * height / glyph.height))
    return glyph.resize((width, height), Image.LANCZOS)


def _composite(canvas, image, x, y):
    """Compone image sobre canvas en (x, y). Lo que se sale por un borde se recorta."""
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(image, (x, y))
    canvas.alpha_composite(layer)


def _draw_pieces(canvas, x, baseline, pieces, font, color):
    """Dibuja los trozos de una palabra con la línea base en baseline. Devuelve la x final."""
    draw = ImageDraw.Draw(canvas)
    ascent, _descent = _line_metrics(font)
    height = _box_height(font)
    for kind, text in pieces:
        if kind == "emoji":
            image = _emoji_image(text, height)
            if image is not None:
                _composite(canvas, image, round(x), round(baseline - ascent))
                x += image.width
        else:
            draw.text((x, baseline), text, font=font, fill=color, anchor="ls")
            x += font.getlength(text)
    return x


def _draw_line(canvas, x, baseline, line, font, color):
    """Dibuja una línea de palabras separadas por un espacio. Devuelve la x final."""
    space = font.getlength(" ")
    for index, pieces in enumerate(line):
        if index:
            x += space
        x = _draw_pieces(canvas, x, baseline, pieces, font, color)
    return x


def _pill(headline, pill_width, scale, warnings):
    """Píldora blanca de esquinas redondeadas con el titular en negro, hasta 2 líneas."""
    px = HEADLINE_PX * scale
    padding_x, padding_y = round(28 * scale), round(12 * scale)
    max_text_width = pill_width - 2 * padding_x
    font = _font(MEDIUM, px)
    lines = _wrap(headline, MEDIUM, font, max_text_width, warnings)
    while len(lines) > 2 and px > 40 * scale:
        px -= 2
        font = _font(MEDIUM, px)
        lines = _wrap(headline, MEDIUM, font, max_text_width, warnings)
    ascent, descent = _line_metrics(font)
    line_height = round((ascent + descent) * 1.1)
    height = 2 * padding_y + line_height * len(lines)
    canvas = Image.new("RGBA", (pill_width, height), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).rounded_rectangle((0, 0, pill_width - 1, height - 1),
                                              radius=round(PILL_RADIUS * scale), fill="#FFFFFF")
    baseline = padding_y + ascent
    for line in lines:
        x = (pill_width - _line_width(line, font)) / 2
        _draw_line(canvas, x, baseline, line, font, "#000000")
        baseline += line_height
    return canvas


def _kicker(text, pill_width, scale, warnings):
    """Texto blanco centrado encima de la píldora, sin fondo."""
    px = HEADLINE_PX * scale
    font = _font(MEDIUM, px)
    ascent, descent = _line_metrics(font)
    line = [_pieces(text, MEDIUM, warnings)]
    text_width = _line_width(line, font)
    canvas = Image.new("RGBA", (max(1, min(round(text_width) + 4, pill_width)), ascent + descent + 4), (0, 0, 0, 0))
    _draw_line(canvas, (canvas.width - text_width) / 2, ascent + 2, line, font, "#FFFFFF")
    return canvas


def _news_bar(text, color, scale, bold, tilt, warnings):
    """Barra de color con el texto en blanco. Con tilt, se gira en sentido antihorario."""
    px = 44 * scale if bold else 40 * scale
    name = BOLD if bold else MEDIUM
    font = _font(name, px)
    label = text.upper() if bold else text
    padding_x, padding_y = round(16 * scale), round(10 * scale)
    ascent, descent = _line_metrics(font)
    line = [_pieces(label, name, warnings)]
    width = round(_line_width(line, font)) + 2 * padding_x
    height = ascent + descent + 2 * padding_y
    bar = Image.new("RGBA", (width, height), color)
    _draw_line(bar, padding_x, padding_y + ascent, line, font, "#FFFFFF")
    if tilt:
        bar = bar.rotate(tilt, expand=True, resample=Image.BICUBIC)
    return bar
