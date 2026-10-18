"""Agrupa palabras en frases, marca el énfasis de cada frase y parte las líneas por ancho real."""

import re
from collections import namedtuple

from engine.stopwords import is_stopword
from engine.styles import shown_texts
from engine.textmetrics import css_scale, text_width

# Alto al que se refieren los valores de estilo (font_size, márgenes, bordes, sombra y blur).
REFERENCE_HEIGHT = 1920
_CLOSING_MARKS = "\"'”’»)]"
_NON_LETTER = re.compile(r"[\W\d_]")

# Un tramo de texto: familia, negrita, cursiva, em y espaciado en px de referencia y el tamaño que pide
# libass (Fontsize). Con exact_metrics, em = fontsize × css_scale, que es lo que dibuja libass.
Run = namedtuple("Run", "family bold italic em spacing fontsize")


def layout_scale(height):
    """Factor que lleva los valores de referencia a un video de esa altura."""
    return height / REFERENCE_HEIGHT


def ends_sentence(text, closes=".?!"):
    """True si la palabra termina con un signo de closes. Ignora comillas y paréntesis finales."""
    return bool(closes) and text.rstrip(_CLOSING_MARKS).endswith(tuple(closes))


def usable_width(style, width, height):
    """Ancho útil de una línea: el video menos márgenes laterales y borde, ya escalados."""
    scale = layout_scale(height)
    return width - 2 * style["margin_h"] * scale - 2 * style["outline_width"] * scale


def italic_on(style):
    return style["emphasis"] in ("italic", "italic_color")


def italic_scale(style):
    """Compresión horizontal de la cursiva en %: scale_x_italic o, si es null, scale_x."""
    value = style["scale_x_italic"]
    return style["scale_x"] if value is None else value


def base_run(style):
    """Tramo normal del estilo, con el tamaño en px de referencia (em) y el de libass (fontsize)."""
    family, bold = style["font_family"], style["font_bold"]
    factor = css_scale(family, bold) if style["exact_metrics"] else 1.0
    return Run(family, bold, False, style["font_size"] * factor, style["letter_spacing"], style["font_size"])


def emphasis_run(style):
    """Tramo enfatizado: con emphasis_font_family es otra familia, sin ella es la del texto normal.

    El em es el del tramo normal por emphasis_size_scale. El espaciado es emphasis_letter_spacing o, si
    es null, el del tramo normal.
    """
    base = base_run(style)
    has_family = style["emphasis_font_family"] is not None
    family = style["emphasis_font_family"] if has_family else base.family
    bold = False if has_family else base.bold
    italic = style["emphasis_italic"]
    em = base.em * style["emphasis_size_scale"]
    spacing = base.spacing if style["emphasis_letter_spacing"] is None else style["emphasis_letter_spacing"]
    factor = css_scale(family, bold, italic) if style["exact_metrics"] else 1.0
    return Run(family, bold, italic, em, spacing, em / factor)


def emphasized_indices(members, style):
    """Palabras del grupo que llevan énfasis por el motor de longitud o por marca manual.

    Las marcadas con "emph" en words.json mandan. Sin marcas y con emphasis_engine "length", con
    emphasis_auto se elige la palabra más larga que no sea stopword (en empate, la primera) y solo en
    grupos de 2 o más palabras. Con "lexicon" el grupo solo devuelve sus marcas manuales: el léxico
    se aplica después, sobre todas las frases (ver layout.build_segments).
    """
    if style["emphasis"] == "none":
        return set()
    flagged = {index for index, word in enumerate(members) if word.get("emph") is True}
    if flagged:
        return flagged
    if style["emphasis_engine"] == "lexicon" or not style["emphasis_auto"] or len(members) < 2:
        return set()
    best, best_len = None, 0
    for index, word in enumerate(members):
        if word.get("emph") is False:
            continue
        core = _NON_LETTER.sub("", word["text"])
        if not core or is_stopword(core):
            continue
        if len(core) > best_len:
            best, best_len = index, len(core)
    return set() if best is None else {best}


def italic_flags(members, emph, style):
    """Qué palabras se miden como tramo enfatizado. En karaoke la activa puede ir en cursiva: se mide todo así."""
    if not italic_on(style):
        return [False] * len(members)
    if style["mode"] == "karaoke":
        return [True] * len(members)
    return [index in emph for index in range(len(members))]


def space_width(style, height):
    """Ancho del espacio entre palabras a la escala del alto, con word_space_scale aplicado."""
    base = base_run(style)
    space = text_width(" ", base.family, base.bold, base.em * layout_scale(height), kerning=style["exact_metrics"])
    if style["word_space_scale"] != 100:
        space *= style["word_space_scale"] / 100
    return space


def line_measure(style, width, height, max_chars=None):
    """Devuelve (medida, límite) para partir líneas.

    La medida recibe pares (texto, enfatizada) y da el ancho en píxeles a la escala del alto, con la
    compresión horizontal (scale_x y scale_x_italic), word_space_scale y el espaciado de cada tramo. El
    texto ya es el que se dibuja (ver styles.shown_texts). Con max_chars cuenta caracteres en vez de píxeles.
    """
    if max_chars is not None:
        return (lambda items: len(" ".join(text for text, _ in items))), max_chars
    scale = layout_scale(height)
    exact = style["exact_metrics"]
    base, emphasis = base_run(style), emphasis_run(style)
    space = space_width(style, height)
    regular_x = style["scale_x"] / 100
    italic_x = italic_scale(style) / 100

    def measure(items):
        tokens = [(text, emphasized) for text, emphasized in items if text]
        total = 0.0
        for index, (token, emphasized) in enumerate(tokens):
            if index:
                total += space
            run = emphasis if emphasized else base
            glyphs = text_width(token, run.family, run.bold, run.em * scale, italic=run.italic, kerning=exact)
            glyphs += run.spacing * scale * len(token)
            total += glyphs * (italic_x if emphasized else regular_x)
        return total

    return measure, usable_width(style, width, height)


def wrap_lines(items, measure, limit):
    """Índices de palabras por línea, en orden greedy. items son pares (texto, cursiva).

    Una palabra que no cabe sola en una línea queda sola: nunca se parte.
    """
    lines = []
    line = []
    for index, item in enumerate(items):
        if line and measure([items[i] for i in line] + [item]) > limit:
            lines.append(line)
            line = []
        line.append(index)
    if line:
        lines.append(line)
    return lines


def balanced_lines(items, measure, limit):
    """Como wrap_lines, pero si el resultado son dos líneas, el corte es el de anchos más parecidos.

    Solo cambia el corte: una página que cabe en una línea sigue en una, y las dos líneas cumplen el límite.
    """
    greedy = wrap_lines(items, measure, limit)
    if len(greedy) != 2:
        return greedy
    best = None
    for cut in range(1, len(items)):
        first, second = list(range(cut)), list(range(cut, len(items)))
        first_width = measure([items[i] for i in first])
        second_width = measure([items[i] for i in second])
        if first_width > limit or second_width > limit:
            continue
        gap = abs(first_width - second_width)
        if best is None or gap < best[0]:
            best = (gap, [first, second])
    return greedy if best is None else best[1]


def lines_for(items, measure, limit, style):
    """Cortes de líneas del estilo: voraces, o equilibrados si balance_lines."""
    if style["balance_lines"]:
        return balanced_lines(items, measure, limit)
    return wrap_lines(items, measure, limit)


def with_shown(words, style):
    """Copias de las palabras con "shown": el texto que se dibuja, con caso y signos ya aplicados."""
    return [{**word, "shown": text} for word, text in zip(words, shown_texts(words, style))]


def group_words(words, style, width, height, max_chars=None):
    """Parte las palabras en frases {"first", "start", "end", "words", "emph", "italic", "lines"}.

    "first" es el índice de la primera palabra dentro de words; "lines" guarda índices dentro de
    "words"; "emph" y "italic" son índices y cursivas por palabra. Una frase se corta al llegar a
    max_words_per_line; tras una pausa mayor que pause_split_s, si ya tiene pause_split_min_words
    palabras; antes de un conector de split_before_words, con la misma condición de palabras mínimas;
    después de un signo de punctuation_closes; y antes de pasar de max_lines líneas o del ancho útil.
    max_chars (o style["max_chars"] si es None) mide caracteres en vez de píxeles. Con merge_orphans, una
    palabra sola sin puntuación se pega a la frase anterior si cabe y el hueco es menor que blank_gap_s
    (ver _fits_together).
    """
    if max_chars is None:
        max_chars = style["max_chars"]
    words = with_shown(words, style)
    measure, limit = line_measure(style, width, height, max_chars)
    chunks = _split(words, style, measure, limit)
    if style["merge_orphans"]:
        chunks = _merge_orphans(chunks, style, measure, limit)
    return [_make_group(members, first, style, measure, limit) for first, members in chunks]


def with_emphasis(group, emph, style, measure, limit):
    """El mismo grupo con otro énfasis, o None si con esa cursiva no cabe en max_lines."""
    members = group["words"]
    lines = lines_for(_items(members, emph, style), measure, limit, style)
    if len(lines) > style["max_lines"]:
        return None
    return {**group, "emph": emph, "italic": italic_flags(members, emph, style), "lines": lines}


def _split(words, style, measure, limit):
    chunks = []
    current, first = [], 0
    for index, word in enumerate(words):
        if current and _must_break(current, word, style, measure, limit):
            chunks.append((first, current))
            current = []
        if not current:
            first = index
        current.append(word)
        if ends_sentence(word["text"], style["punctuation_closes"]):
            chunks.append((first, current))
            current = []
    if current:
        chunks.append((first, current))
    return chunks


def _items(members, emph, style):
    flags = italic_flags(members, emph, style)
    return [(word["shown"], flag) for word, flag in zip(members, flags)]


def _bare(text):
    """Solo las letras de la palabra, en minúsculas: «Because,» -> «because»."""
    return "".join(char for char in text.lower() if char.isalpha())


def _opens_clause(word, style):
    connectors = style["split_before_words"]
    return bool(connectors) and _bare(word["text"]) in {_bare(item) for item in connectors}


def _must_break(current, word, style, measure, limit):
    pause = word["start"] - current[-1]["end"]
    if len(current) >= style["pause_split_min_words"]:
        if pause > style["pause_split_s"] or _opens_clause(word, style):
            return True
    if len(current) >= style["max_words_per_line"]:
        return True
    members = current + [word]
    items = _items(members, emphasized_indices(members, style), style)
    if len(wrap_lines(items, measure, limit)) > style["max_lines"]:
        return True
    return _soft_limit_reached(current, word, members, style)


def _soft_limit_reached(current, word, members, style):
    """Tope blando: la frase se corta al llegar a target_words o al pasar soft_max_chars.

    Solo se llega aquí si la unión cabe en los topes duros (max_words_per_line, max_chars y max_lines). Una
    palabra corta (hang_max_chars) se queda al final de la frase en vez de abrir la siguiente. Con target_words,
    solo se queda cuando la frase está justo en el objetivo, para no encadenar palabras cortas.
    """
    target = style["target_words"]
    over_words = target is not None and len(current) >= target
    soft_chars = style["soft_max_chars"]
    over_chars = soft_chars is not None and len(" ".join(item["shown"] for item in members)) > soft_chars
    if not (over_words or over_chars):
        return False
    if _is_hanging(word, style) and (over_chars or len(current) == target):
        return False
    return True


def _is_hanging(word, style):
    """Palabra corta de hang_max_chars letras o menos. 0 desactiva el colgado."""
    core = _bare(word["text"])
    return 0 < len(core) <= style["hang_max_chars"]


def _merge_orphans(chunks, style, measure, limit):
    """Pega cada frase de una sola palabra sin puntuación a la anterior, si cabe y no hay pausa."""
    merged = []
    for first, members in chunks:
        if merged and _is_orphan(members, style) and _fits_together(merged[-1][1], members, style, measure, limit):
            previous_first, previous = merged[-1]
            merged[-1] = (previous_first, previous + members)
        else:
            merged.append((first, members))
    return merged


def _is_orphan(members, style):
    return len(members) == 1 and not ends_sentence(members[0]["text"], style["punctuation_closes"])


def _fits_together(previous, members, style, measure, limit):
    """Une solo si la frase anterior no cierra con puntuación, el hueco es menor que la pausa de
    unión (blank_gap_s, o pause_split_s sin él) y la unión cabe en max_words, max_chars o píxeles y max_lines.
    Una huérfana cortada por un corte de palabras o de caracteres nunca cabe; por eso la unión
    solo recupera las cortadas por una pausa corta."""
    closes = style["punctuation_closes"]
    if ends_sentence(previous[-1]["text"], closes):
        return False
    join_gap = style["blank_gap_s"] if style["blank_gap_s"] is not None else style["pause_split_s"]
    if members[0]["start"] - previous[-1]["end"] > join_gap:
        return False
    combined = previous + members
    if len(combined) > style["max_words_per_line"]:
        return False
    items = _items(combined, emphasized_indices(combined, style), style)
    return len(wrap_lines(items, measure, limit)) <= style["max_lines"]


def _make_group(members, first, style, measure, limit):
    emph = emphasized_indices(members, style)
    return {
        "first": first,
        "start": members[0]["start"],
        "end": members[-1]["end"],
        "words": members,
        "emph": emph,
        "italic": italic_flags(members, emph, style),
        "lines": lines_for(_items(members, emph, style), measure, limit, style),
    }
