"""Genera el archivo ASS (v4+) de un job a partir de los segmentos de engine.layout.

build_ass() calcula los segmentos con build_segments() y los dibuja. render_ass() dibuja segmentos ya
calculados, por ejemplo los que devuelve timeline.segments_from_markup().

Con line_height, o en karaoke_box, cada línea es un evento con su posición de engine.geometry: el paso
entre líneas es el del estilo y no el de libass. En reveal, cada ventana de palabra es un evento con el
bloque entero: las palabras futuras van ocultas con \\alpha y la nueva se funde con \\t. En karaoke_box,
la caja de la palabra activa es un dibujo \\p1 en la capa 0 y el texto de la página va encima.
"""

from engine.grouping import base_run, emphasis_run, italic_on, italic_scale, layout_scale
from engine.layout import build_segments

# ASS no define escapes para llaves ni para la barra invertida. Se sustituyen por
# equivalentes de ancho completo para que el texto nunca abra una etiqueta ni forme \N.
_TEXT_SUBSTITUTIONS = str.maketrans({"{": "｛", "}": "｝", "\\": "＼"})

_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
    "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
    "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
)
_EVENT_FORMAT = "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
# Cuarto de círculo con cubicas: el punto de control queda a 0.5523 del radio.
_KAPPA = 0.5523


def bgr_hex(color):
    """#RRGGBB -> BBGGRR, el orden de color que usa ASS."""
    return (color[5:7] + color[3:5] + color[1:3]).upper()


def ass_color(color, alpha=0):
    """#RRGGBB -> &HAABBGGRR. En ASS el alfa es inverso: 0 es opaco y 255 transparente."""
    return f"&H{alpha:02X}{bgr_hex(color)}"


def escape_text(text):
    return text.translate(_TEXT_SUBSTITUTIONS)


def ass_time(seconds):
    """Segundos -> H:MM:SS.cc."""
    centis = round(seconds * 100)
    hours, rest = divmod(centis, 360000)
    minutes, rest = divmod(rest, 6000)
    secs, centis = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _num(value):
    return f"{value:g}"


def _scale(value, sx=100):
    """Escala en x e y como etiquetas ASS. value ya incluye el ajuste de fit; sx es la compresión horizontal en %."""
    return f"\\fscx{_num(value * sx / 100)}\\fscy{_num(value)}"


def _fit_tag(percent, sx=100):
    """Escala de ajuste al inicio del evento. Vacía si el grupo cabe sin reducir."""
    return "" if percent == 100 else "{" + _scale(percent, sx) + "}"


def _alpha(opacity):
    """Opacidad de 0 a 1 -> alfa ASS: 0 es opaco y 255 transparente."""
    return round((1 - opacity) * 255)


def _phrase_pop(k, sx=100):
    """Pop de frase: 112 % y de vuelta al 100 %, en 220 ms. k multiplica ambas escalas (1 sin ajuste)."""
    return f"\\t(0,110,{_scale(112 * k, sx)})\\t(110,220,{_scale(100 * k, sx)})"


def _word_pop(k, sx=100):
    """Pulso de la palabra activa en karaoke, en 180 ms, con el mismo criterio de escala."""
    return f"\\t(0,90,{_scale(112 * k, sx)})\\t(90,180,{_scale(100 * k, sx)})"


def _animation_tag(animation, k=1.0, sx=100):
    if animation == "pop":
        return "{" + _phrase_pop(k, sx) + "}"
    if animation == "fade":
        return "{\\fad(80,0)}"
    return ""


ANIMATION_TAGS = {name: _animation_tag(name) for name in ("none", "pop", "fade")}
PHRASE_POP = _phrase_pop(1.0)
WORD_POP = _word_pop(1.0)


def build_ass(words, style, width, height):
    """Devuelve el texto ASS completo. style viene de styles.resolve().

    Los valores de estilo son píxeles de un video de 1080x1920; aquí se escalan por alto/1920.
    """
    width, height = _size(width, height)
    return render_ass(build_segments(words, style, width, height), style, width, height)


def render_ass(segments, style, width, height):
    """Texto ASS de segmentos ya calculados. Cada segmento tiene la forma que documenta engine.layout."""
    width, height = _size(width, height)
    scale = layout_scale(height)
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        _STYLE_FORMAT,
        _style_line(style, scale),
        "",
        "[Events]",
        _EVENT_FORMAT,
    ]
    for segment in segments:
        for layer, start, end, text in _events(segment, style, width, height, scale):
            lines.append(_dialogue(start, end, text, layer))
    return "\n".join(lines) + "\n"


def _size(width, height):
    width, height = int(width), int(height)
    if width <= 0 or height <= 0:
        raise ValueError("width y height deben ser positivos")
    return width, height


def _style_line(style, scale):
    if style["box_color"] is not None:
        # Con BorderStyle=3 libass dibuja la caja con OutlineColour o BackColour según la versión.
        # Los dos llevan el mismo color y alfa para no depender de cuál.
        box = ass_color(style["box_color"], _alpha(style["box_opacity"]))
        outline_colour = back_colour = box
        border_style = 3
    elif style["shadow_style"] == "halo":
        # Halo: el contorno es la sombra, con su opacidad. La sombra de ASS queda transparente y sin desplazamiento.
        outline_colour = ass_color(style["shadow_color"], _alpha(style["shadow_opacity"]))
        back_colour = ass_color(style["shadow_color"], 255)
        border_style = 1
    else:
        outline_colour = ass_color(style["outline_color"])
        back_colour = ass_color(style["shadow_color"], _alpha(style["shadow_opacity"]))
        border_style = 1
    if style["shadow_style"] in ("soft", "halo"):
        shadow = 0  # la sombra suave va en una capa aparte, y el halo va en el contorno
    else:
        shadow = style["shadow_depth"] * scale
    if style["mode"] == "karaoke_sweep":
        # \kf pinta de SecondaryColour a PrimaryColour, así que el resaltado va en Primary.
        primary, secondary = style["highlight_color"], style["text_color"]
    else:
        primary, secondary = style["text_color"], style["highlight_color"]
    positioned = style["y_pct"] is not None
    if positioned:
        alignment = "5" if style["text_align"] == "center" else "4"
    else:
        alignment = str(style["alignment"])
    margin_h = str(round(style["margin_h"] * scale))
    fields = [
        "Default",
        style["font_family"],
        _num(round(style["font_size"] * scale, 2)),
        ass_color(primary),
        ass_color(secondary),
        outline_colour,
        back_colour,
        "-1" if style["font_bold"] else "0",
        "0", "0", "0",  # Italic, Underline, StrikeOut
        _num(style["scale_x"]), "100",  # ScaleX, ScaleY
        "0", "0",  # Spacing, Angle: el espaciado va como \fsp en cada evento
        str(border_style),
        _num(round(style["outline_width"] * scale, 2)),
        _num(round(shadow, 2)),
        alignment,
        margin_h,
        margin_h,
        "0" if positioned else str(round(style["margin_v"] * scale)),
        "1",
    ]
    return "Style: " + ",".join(fields)


def _text_tags(style, scale):
    """Etiquetas de texto de cada evento: blur del halo y espaciado entre letras."""
    tags = []
    if style["shadow_style"] == "halo":
        tags.append(f"\\blur{_num(round(style['shadow_blur'] * scale, 2))}")
    if style["letter_spacing"] != 0:
        tags.append(f"\\fsp{_num(round(style['letter_spacing'] * scale, 2))}")
    return tags


def _head(style, width, height, scale):
    """Etiquetas al inicio de cada evento sin posición por línea: posición fija (y_pct), blur y espaciado."""
    tags = []
    if style["y_pct"] is not None:
        x = width * style["x_pct"] if style["x_pct"] is not None else width / 2
        tags.append(f"\\pos({round(x)},{round(height * style['y_pct'])})")
    tags.extend(_text_tags(style, scale))
    return "{" + "".join(tags) + "}" if tags else ""


def _per_line(style):
    """True si cada línea va en su propio evento con su posición: al fijar line_height o en karaoke_box."""
    return style["line_height"] is not None or style["mode"] == "karaoke_box"


def _line_head(segment, style, scale, number):
    """Posición de una línea: \\an7 en el borde izquierdo o \\an8 al centro, con su borde superior en ASS."""
    layout = segment["layout"]
    line = layout["lines"][number]
    anchor = layout["anchor"]
    top = (line["baseline"] - line["ascent"]) * scale
    if anchor["align"] == "left":
        align, x = 7, line["x"] * scale
    else:
        align, x = 8, anchor["x"] * scale
    tags = [f"\\an{align}", f"\\pos({_num(round(x, 2))},{_num(round(top, 2))})"] + _text_tags(style, scale)
    return "{" + "".join(tags) + "}"


def _blocks(segment, style, width, height, scale, anim=""):
    """Bloques de un tramo como (prefijo, líneas). Con posición por línea, cada línea es un bloque."""
    fit_tag = _fit_tag(segment["fit"], style["scale_x"])
    if _per_line(style):
        return [(_line_head(segment, style, scale, number) + fit_tag + anim, [line])
                for number, line in enumerate(segment["lines"])]
    return [(_head(style, width, height, scale) + fit_tag + anim, segment["lines"])]


def _events(segment, style, width, height, scale):
    """Eventos (capa, inicio, fin, texto) de un segmento."""
    events = []
    first = 0
    if style["mode"] == "karaoke_box":
        events.extend(_box_events(segment, style, scale))
        first = 1  # el texto va encima de la caja: capa 1 con sombra, o capa 1 sin ella
    for start, end, prefix, body, shade in _specs(segment, style, width, height, scale):
        if style["shadow_style"] == "soft":
            events.append((first, start, end, _soft_block(style, scale) + prefix + shade))
            events.append((first + 1, start, end, prefix + body))
        else:
            events.append((first, start, end, prefix + body))
    return events


def _specs(segment, style, width, height, scale):
    """Tramos de texto de un segmento como (inicio, fin, prefijo, texto nítido, texto de la sombra)."""
    mode = style["mode"]
    tags = _Tags(style, segment["fit"], scale)
    if mode == "karaoke":
        return _karaoke_specs(segment, style, width, height, scale, tags)
    if mode == "karaoke_sweep":
        fit, sx = segment["fit"], style["scale_x"]
        anim = _animation_tag(style["animation"], fit / 100, sx)
        body = _render_text(segment, _sweep_decorator(segment, style, tags), tags)
        shade = _render_text(segment, _copy_decorator(_copy_italic(segment, style, None), tags, style), tags)
        prefix = _head(style, width, height, scale) + _fit_tag(fit, sx) + anim
        return [(segment["start"], segment["end"], prefix, body, shade)]
    if mode == "reveal":
        return _reveal_specs(segment, style, width, height, scale, tags)
    anim = ""
    if mode == "phrase":
        anim = _animation_tag(style["animation"], segment["fit"] / 100, style["scale_x"])
    specs = []
    decorate = _static_decorator(segment, style, tags)
    shading = _copy_decorator(_copy_italic(segment, style, None), tags, style)
    for prefix, lines in _blocks(segment, style, width, height, scale, anim):
        body = _render_lines(lines, decorate, tags)
        if not body and _per_line(style):
            continue
        shade = _render_lines(lines, shading, tags)
        specs.append((segment["start"], segment["end"], prefix, body, shade))
    return specs


def _karaoke_specs(segment, style, width, height, scale, tags):
    fit, sx = segment["fit"], style["scale_x"]
    k = fit / 100
    head = _head(style, width, height, scale)
    anim = _animation_tag(style["animation"], k, sx)
    specs = []
    for position, window in enumerate(segment["windows"]):
        first = position == 0
        prefix = head + _fit_tag(fit, sx) + (anim if first else "")
        body = _render_text(segment, _karaoke_decorator(window["index"], segment, style, first, k, tags), tags)
        shade = _render_text(segment, _copy_decorator(_copy_italic(segment, style, window["index"]), tags, style), tags)
        specs.append((window["start"], window["end"], prefix, body, shade))
    return specs


def _reveal_specs(segment, style, width, height, scale, tags):
    """Un evento por ventana de palabra y bloque: el bloque entero, con las palabras ya dichas visibles."""
    specs = []
    for window in segment["windows"]:
        body_decorate = _reveal_decorator(segment, style, tags, window["index"], shade=False)
        shade_decorate = _reveal_decorator(segment, style, tags, window["index"], shade=True)
        for prefix, lines in _blocks(segment, style, width, height, scale):
            body = _render_lines(lines, body_decorate, tags)
            if not body and _per_line(style):
                continue
            specs.append((window["start"], window["end"], prefix, body, _render_lines(lines, shade_decorate, tags)))
    return specs


def _box_events(segment, style, scale):
    """Caja de la palabra activa en karaoke_box: un dibujo \\p1 con esquinas redondeadas, en la capa 0."""
    radius = style["highlight_box_radius"] * scale
    color = style["highlight_box_color"] or style["highlight_color"]
    boxes = {box["index"]: box for box in segment["boxes"]}
    events = []
    for window in segment["windows"]:
        box = boxes.get(window["index"])
        if box is None:
            continue
        path = _rounded_rect(box["w"] * scale, box["h"] * scale, radius)
        x, y = _num(round(box["x"] * scale, 2)), _num(round(box["y"] * scale, 2))
        # \fscx100: el dibujo no hereda el ScaleX del estilo (scale_x comprime el texto, no la caja).
        text = f"{{\\an7\\pos({x},{y})\\bord0\\shad0\\fscx100\\1c&H{bgr_hex(color)}&\\1a&H00&\\p1}}{path}"
        events.append((0, window["start"], window["end"], text))
    return events


def _rounded_rect(width, height, radius):
    """Dibujo ASS de un rectángulo de esquinas redondeadas, con el origen en su esquina superior izquierda."""
    def f(value):
        return _num(round(value, 2))

    radius = min(radius, width / 2, height / 2)
    if radius <= 0:
        return f"m 0 0 l {f(width)} 0 l {f(width)} {f(height)} l 0 {f(height)}"
    k = _KAPPA * radius
    w, h, r = width, height, radius
    return " ".join([
        f"m {f(r)} 0",
        f"l {f(w - r)} 0",
        f"b {f(w - r + k)} 0 {f(w)} {f(r - k)} {f(w)} {f(r)}",
        f"l {f(w)} {f(h - r)}",
        f"b {f(w)} {f(h - r + k)} {f(w - r + k)} {f(h)} {f(w - r)} {f(h)}",
        f"l {f(r)} {f(h)}",
        f"b {f(r - k)} {f(h)} 0 {f(h - r + k)} 0 {f(h - r)}",
        f"l 0 {f(r)}",
        f"b 0 {f(r - k)} {f(r - k)} 0 {f(r)} 0",
    ])


def _soft_block(style, scale):
    """Capa 0 de la sombra suave: sin borde ni sombra de ASS, con blur y el color y alfa de la sombra."""
    blur = _num(round(style["shadow_blur"] * scale, 2))
    return (f"{{\\bord0\\shad0\\blur{blur}\\1c&H{bgr_hex(style['shadow_color'])}&"
            f"\\1a&H{_alpha(style['shadow_opacity']):02X}&}}")


def _run_tags(style, scale):
    """Apertura y cierre del tramo enfatizado cuando cambian su familia, negrita, tamaño o espaciado."""
    base, emphasis = base_run(style), emphasis_run(style)
    open_tags, close_tags = "", ""
    if emphasis.family != base.family:
        open_tags += f"\\fn{emphasis.family}"
        close_tags += f"\\fn{base.family}"
    if emphasis.bold != base.bold:
        open_tags += "\\b1" if emphasis.bold else "\\b0"
        close_tags += "\\b1" if base.bold else "\\b0"
    if emphasis.fontsize != base.fontsize:
        open_tags += f"\\fs{_num(round(emphasis.fontsize * scale, 2))}"
        close_tags += f"\\fs{_num(round(base.fontsize * scale, 2))}"
    if emphasis.spacing != base.spacing:
        open_tags += f"\\fsp{_num(round(emphasis.spacing * scale, 2))}"
        close_tags += f"\\fsp{_num(round(base.spacing * scale, 2))}"
    return open_tags, close_tags


class _Tags:
    """Etiquetas de cursiva, tramo enfatizado y espacio de un evento. fit es el ajuste de fit (fit / 100)."""

    def __init__(self, style, fit, scale):
        k = fit / 100
        regular_x = style["scale_x"] * k
        italic_x = italic_scale(style) * k
        custom_italic = italic_scale(style) != style["scale_x"]
        self.italic_open = "\\i1" + (f"\\fscx{_num(italic_x)}" if custom_italic else "")
        self.italic_close = "\\i0" + (f"\\fscx{_num(regular_x)}" if custom_italic else "")
        self.run_open, self.run_close = _run_tags(style, scale)
        # Cada espacio entre palabras lleva su propio \fscx y vuelve a la escala normal.
        if style["word_space_scale"] != 100:
            space_x = style["word_space_scale"] * k
            self.separator = "{\\fscx%s} {\\fscx%s}" % (_num(space_x), _num(regular_x))
        else:
            self.separator = " "


def _italic_and_run(style, tags):
    """Tramo enfatizado sin color: cursiva si la lleva, más su familia, tamaño y espaciado propios."""
    open_tags, close_tags = "", ""
    if italic_on(style) and emphasis_run(style).italic:
        open_tags, close_tags = tags.italic_open, tags.italic_close
    return open_tags + tags.run_open, close_tags + tags.run_close


def _emphasis_tags(style, tags):
    """Apertura y cierre del énfasis fijo: cursiva, tramo propio y/o color de resaltado."""
    open_tags, close_tags = _italic_and_run(style, tags)
    if style["emphasis"] in ("color", "italic_color"):
        open_tags += "\\c&H" + bgr_hex(style["highlight_color"]) + "&"
        close_tags += "\\c&H" + bgr_hex(style["text_color"]) + "&"
    return open_tags, close_tags


def _emphasized(segment):
    return {word["index"] for line in segment["lines"] for word in line if word["emph"]}


def _static_decorator(segment, style, tags):
    open_tags, close_tags = _emphasis_tags(style, tags)
    emph = _emphasized(segment)

    def decorate(index, token):
        if index not in emph or not open_tags:
            return token
        return "{" + open_tags + "}" + token + "{" + close_tags + "}"

    return decorate


def _karaoke_decorator(active, segment, style, first, k, tags):
    """Palabra activa: color de resaltado, itálica si el énfasis la incluye y, con pop, su pulso.

    El cierre no usa \\r, que quitaría el pop de frase del resto de la línea.
    """
    static = _static_decorator(segment, style, tags)
    sx = style["scale_x"]
    base = bgr_hex(style["text_color"])
    highlight = bgr_hex(style["highlight_color"])
    italic = italic_on(style)
    open_tags = (tags.italic_open if italic else "") + f"\\c&H{highlight}&"
    close_tags = tags.italic_close if italic else ""
    if style["animation"] == "pop":
        open_tags += _word_pop(k, sx)
        close_tags += f"\\c&H{base}&" + (_phrase_pop(k, sx) if first else _scale(100 * k, sx))
    else:
        close_tags += f"\\c&H{base}&"
    opening, closing = "{" + open_tags + "}", "{" + close_tags + "}"

    def decorate(index, token):
        if index == active:
            return opening + token + closing
        return static(index, token)

    return decorate


def _sweep_decorator(segment, style, tags):
    """Barrido \\kf de cada palabra. Un silencio antes de una palabra se marca con {\\kNN} vacío,
    así el barrido no se adelanta a la voz."""
    static = _static_decorator(segment, style, tags)
    by_index = {word["index"]: word for line in segment["lines"] for word in line}

    def decorate(index, token):
        word = by_index[index]
        previous = by_index.get(index - 1)
        centis = round((word["end"] - word["start"]) * 100)
        gap = round((word["start"] - previous["end"]) * 100) if previous is not None else 0
        prefix = f"{{\\k{gap}}}" if gap > 0 else ""
        return prefix + f"{{\\kf{centis}}}" + static(index, token)

    return decorate


def _copy_italic(segment, style, active):
    """Palabras con tramo propio en la sombra: las mismas que en el texto nítido, sin colores."""
    if not italic_on(style):
        return set()
    marked = _emphasized(segment)
    if active is not None:
        marked.add(active)
    return marked


def _copy_decorator(indices, tags, style):
    """Copia de la sombra: las palabras de indices llevan el mismo tramo que el texto, sin el color."""
    open_tags, close_tags = _italic_and_run(style, tags)

    def decorate(index, token):
        if index in indices and open_tags:
            return "{" + open_tags + "}" + token + "{" + close_tags + "}"
        return token

    return decorate


def _reveal_target(style, shade):
    """Valores que toma la palabra activa al fundirse. La sombra y el halo se funden a su propio alfa."""
    opacity = _alpha(style["shadow_opacity"])
    if shade:
        return f"\\1a&H{opacity:02X}&"
    halo = style["shadow_style"] == "halo"
    outline = opacity if halo else 0
    back = 255 if halo else opacity
    return f"\\1a&H00&\\3a&H{outline:02X}&\\4a&H{back:02X}&"


def _reveal_decorator(segment, style, tags, active, shade):
    """Palabras de una ventana: las anteriores visibles, la activa con fundido y las siguientes ocultas.

    \\alpha&HFF& oculta; la activa se funde con \\t en reveal_fade_ms. La copia de la sombra usa su propio alfa.
    """
    emph = _emphasized(segment)
    if shade:
        open_tags, close_tags = _italic_and_run(style, tags)
    else:
        open_tags, close_tags = _emphasis_tags(style, tags)
    fade = style["reveal_fade_ms"]
    hidden = "\\alpha&HFF&"
    fading = f"{hidden}\\t(0,{fade},{_reveal_target(style, shade)})" if fade else ""

    def decorate(index, token):
        if index < active:
            pre = ""
        elif index == active:
            pre = fading
        else:
            pre = hidden
        if index in emph and open_tags:
            return "{" + open_tags + pre + "}" + token + "{" + close_tags + "}"
        if pre:
            return "{" + pre + "}" + token
        return token

    return decorate


def _render_lines(lines, decorate, tags):
    """Une las palabras de cada línea con espacios (o con word_space_scale) y las líneas con \\N."""
    rows = []
    for line in lines:
        tokens = []
        for word in line:
            token = escape_text(word["display"])
            if token:
                tokens.append(decorate(word["index"], token))
        if tokens:
            rows.append(tags.separator.join(tokens))
    return r"\N".join(rows)


def _render_text(segment, decorate, tags):
    return _render_lines(segment["lines"], decorate, tags)


def _dialogue(start, end, text, layer=0):
    return f"Dialogue: {layer},{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{text}"
