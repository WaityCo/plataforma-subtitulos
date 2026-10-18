"""Estilo de subtítulos: defaults del motor, presets desde JSON y validación estricta."""

import json
import math
import re
import warnings
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

PRESETS_PATH = Path(__file__).resolve().parent.parent / "presets" / "presets.json"

MODES = ("phrase", "karaoke", "karaoke_sweep", "karaoke_box", "reveal")
ANIMATIONS = ("none", "pop", "fade")
EMPHASES = ("none", "italic", "color", "italic_color")
SHADOW_STYLES = ("hard", "soft", "halo")
EMPHASIS_ENGINES = ("length", "lexicon")
TEXT_CASES = ("as_is", "upper", "lower_smart")
TEXT_ALIGNS = ("left", "center")

# Base de todo estilo. Coincide con ken_classic para que un override parcial siempre sea válido.
# Los campos nuevos de ken_remedie tienen defaults que no cambian el comportamiento de los demás presets.
DEFAULT_STYLE = {
    "font_family": "Montserrat",
    "font_bold": True,
    "font_size": 86,
    "uppercase": False,
    "strip_punctuation": False,
    "text_case": "as_is",
    "exact_metrics": False,
    "text_color": "#FFFFFF",
    "highlight_color": "#FFD400",
    "outline_color": "#000000",
    "outline_width": 8,
    "shadow_depth": 2,
    "box_color": None,
    "box_opacity": 0.6,
    "alignment": 2,
    "margin_v": 420,
    "margin_h": 80,
    "mode": "karaoke",
    "max_words_per_line": 3,
    "max_lines": 2,
    "animation": "pop",
    "emphasis": "none",
    "emphasis_auto": True,
    "emphasis_font_family": None,
    "emphasis_italic": True,
    "emphasis_size_scale": 1.0,
    "emphasis_letter_spacing": None,
    "emphasis_max_per_segment": None,
    "shadow_style": "hard",
    "shadow_color": "#000000",
    "shadow_opacity": 0.55,
    "shadow_blur": 8,
    "scale_x": 100,
    "scale_x_italic": None,
    "letter_spacing": 0,
    "word_space_scale": 100,
    "y_pct": None,
    "x_pct": None,
    "text_align": "center",
    "line_height": None,
    "max_chars": None,
    "target_words": None,
    "hang_max_chars": 0,
    "soft_max_chars": None,
    "punctuation_closes": ".?!",
    "pause_split_s": 0.6,
    "pause_split_min_words": 1,
    "split_before_words": (),
    "merge_orphans": False,
    "balance_lines": False,
    "blank_gap_s": None,
    "tail_s": 0.05,
    "min_duration_s": 0.30,
    "reveal_fade_ms": 100,
    "highlight_box_color": None,
    "highlight_box_radius": 0,
    "highlight_box_padding_x": 0,
    "highlight_box_padding_y": 0,
    "emphasis_engine": "length",
    "emphasis_ratio": None,
}

# Reglas por campo. Los rangos son inclusivos.
_RULES = {
    "font_family": ("text",),
    "font_bold": ("bool",),
    "font_size": ("number", 10, 300),
    "uppercase": ("bool",),
    "strip_punctuation": ("bool",),
    "text_case": ("enum", TEXT_CASES),
    "exact_metrics": ("bool",),
    "text_color": ("color",),
    "highlight_color": ("color",),
    "outline_color": ("color",),
    "outline_width": ("number", 0, 30),
    "shadow_depth": ("number", 0, 20),
    "box_color": ("color_or_null",),
    "box_opacity": ("number", 0, 1),
    "alignment": ("int", 1, 9),
    "margin_v": ("int", 0, 1920),
    "margin_h": ("int", 0, 1080),
    "mode": ("enum", MODES),
    "max_words_per_line": ("int", 1, 20),
    "max_lines": ("int", 1, 3),
    "animation": ("enum", ANIMATIONS),
    "emphasis": ("enum", EMPHASES),
    "emphasis_auto": ("bool",),
    "emphasis_font_family": ("text_or_null",),
    "emphasis_italic": ("bool",),
    "emphasis_size_scale": ("number", 0.1, 5),
    "emphasis_letter_spacing": ("number_or_null", -50, 50),
    "emphasis_max_per_segment": ("int_or_null", 1, 20),
    "shadow_style": ("enum", SHADOW_STYLES),
    "shadow_color": ("color",),
    "shadow_opacity": ("number", 0, 1),
    "shadow_blur": ("number", 0, 50),
    "scale_x": ("number", 10, 300),
    "scale_x_italic": ("number_or_null", 10, 300),
    "letter_spacing": ("number", -50, 50),
    "word_space_scale": ("number", 1, 300),
    "y_pct": ("number_or_null", 0, 1),
    "x_pct": ("number_or_null", 0, 1),
    "text_align": ("enum", TEXT_ALIGNS),
    "line_height": ("number_or_null", 0.5, 3),
    "max_chars": ("int_or_null", 1, 200),
    "target_words": ("int_or_null", 1, 20),
    "hang_max_chars": ("int", 0, 10),
    "soft_max_chars": ("int_or_null", 1, 200),
    "punctuation_closes": ("punct",),
    "pause_split_s": ("number", 0, 10),
    "pause_split_min_words": ("int", 1, 20),
    "split_before_words": ("word_list",),
    "merge_orphans": ("bool",),
    "balance_lines": ("bool",),
    "blank_gap_s": ("number_or_null", 0, 10),
    "tail_s": ("number", 0, 5),
    "min_duration_s": ("number", 0, 5),
    "reveal_fade_ms": ("number", 0, 1000),
    "highlight_box_color": ("color_or_null",),
    "highlight_box_radius": ("number", 0, 100),
    "highlight_box_padding_x": ("number", 0, 100),
    "highlight_box_padding_y": ("number", 0, 100),
    "emphasis_engine": ("enum", EMPHASIS_ENGINES),
    "emphasis_ratio": ("number_or_null", 0, 1),
}

_HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")
# En la línea Style del ASS las comas separan campos; las llaves y los saltos rompen el archivo.
_FORBIDDEN_IN_FAMILY = re.compile(r"[,{}\\\r\n]")
_PRESET_META = ("label", "description")
_EDGE_MARKS = re.compile(r"^\W+|\W+$")
_INNER_MARKS = re.compile(r"[^\w'’]")
# Prefijo de signos, núcleo y sufijo de signos de una palabra. Los apóstrofos internos quedan en el núcleo.
_EDGES = re.compile(r"^(\W*)(.*?)(\W*)$", re.DOTALL)
_CLOSING_MARKS = "\"'”’»)]"
_SENTENCE_END = (".", "?", "!")
_MAX_SPLIT_WORDS = 50


def list_presets():
    """Presets con name, label, description y el estilo resuelto de cada uno."""
    return [
        {
            "name": name,
            "label": preset["label"],
            "description": preset["description"],
            "style": resolve(name),
        }
        for name, preset in _load_presets().items()
    ]


def resolve(preset, overrides=None):
    """Estilo completo: defaults, luego el preset y al final los overrides. Lanza ValueError si algo es inválido."""
    presets = _load_presets()
    if not isinstance(preset, str) or preset not in presets:
        raise ValueError(f"Preset desconocido: {preset!r}. Disponibles: {', '.join(presets)}")
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, Mapping):
        raise ValueError("overrides debe ser un objeto con campos de estilo")
    style = {**DEFAULT_STYLE, **presets[preset]["style"], **_known_fields(overrides, "overrides")}
    _validate_style(style)
    return style


@lru_cache(maxsize=1)
def _load_presets():
    raw = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
    presets = {}
    for name, body in raw.items():
        label, description = body.get("label"), body.get("description")
        if not (_is_text(label) and _is_text(description)):
            raise ValueError(f"El preset {name!r} necesita label y description no vacíos")
        style = _known_fields({k: v for k, v in body.items() if k not in _PRESET_META}, f"preset {name}")
        _validate_style({**DEFAULT_STYLE, **style})
        presets[name] = {"label": label, "description": description, "style": style}
    return presets


def _known_fields(fields, source):
    """Descarta las claves que no son campos de estilo, con warning en vez de error."""
    known = {}
    for key, value in fields.items():
        if key in _RULES:
            known[key] = value
        else:
            warnings.warn(f"Campo de estilo desconocido ignorado en {source}: {key}", stacklevel=3)
    return known


def _validate_style(style):
    for name, value in style.items():
        _validate_field(name, value)


def _validate_field(name, value):
    rule = _RULES[name]
    kind = rule[0]
    if kind == "bool":
        ok, expected = isinstance(value, bool), "true o false"
    elif kind == "int":
        ok = _is_int(value) and rule[1] <= value <= rule[2]
        expected = f"entero entre {rule[1]} y {rule[2]}"
    elif kind == "number":
        ok = _is_number(value) and rule[1] <= value <= rule[2]
        expected = f"número entre {rule[1]} y {rule[2]}"
    elif kind == "color":
        ok, expected = _is_color(value), "color #RRGGBB"
    elif kind == "color_or_null":
        ok, expected = value is None or _is_color(value), "color #RRGGBB o null"
    elif kind == "number_or_null":
        ok = value is None or (_is_number(value) and rule[1] <= value <= rule[2])
        expected = f"número entre {rule[1]} y {rule[2]} o null"
    elif kind == "int_or_null":
        ok = value is None or (_is_int(value) and rule[1] <= value <= rule[2])
        expected = f"entero entre {rule[1]} y {rule[2]} o null"
    elif kind == "punct":
        ok = isinstance(value, str) and len(value) <= 20 and all(not c.isalnum() and not c.isspace() for c in value)
        expected = "texto de signos de puntuación sin letras, números ni espacios"
    elif kind == "enum":
        ok, expected = value in rule[1], "uno de " + ", ".join(rule[1])
    elif kind == "text_or_null":
        ok = value is None or _is_family(value)
        expected = "texto no vacío, sin comas, llaves ni saltos de línea, o null"
    elif kind == "word_list":
        ok = isinstance(value, (list, tuple)) and len(value) <= _MAX_SPLIT_WORDS and all(_is_bare_word(item) for item in value)
        expected = f"lista de hasta {_MAX_SPLIT_WORDS} palabras, cada una sin espacios"
    else:
        ok = _is_family(value)
        expected = "texto no vacío, sin comas, llaves ni saltos de línea"
    if not ok:
        raise ValueError(f"{name} inválido: se esperaba {expected}; llegó {value!r}")


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_color(value):
    return isinstance(value, str) and _HEX_COLOR.fullmatch(value) is not None


def _is_text(value):
    return isinstance(value, str) and value.strip() != ""


def _is_family(value):
    return _is_text(value) and not _FORBIDDEN_IN_FAMILY.search(value)


def _is_bare_word(value):
    return isinstance(value, str) and value.strip() != "" and not any(c.isspace() for c in value.strip())


def text_case_of(style):
    """Caso del texto: uppercase es alias de upper, así que manda sobre text_case."""
    if style["uppercase"]:
        return "upper"
    return style["text_case"]


def display_text(text, style):
    """Texto tal como se dibuja, para una palabra suelta. Con lower_smart, una palabra sin frase es inicio de frase."""
    return _apply_case(text, text_case_of(style), True, style)


def shown_texts(words, style):
    """Texto que se dibuja de cada palabra, en orden. Con lower_smart el caso depende de la frase.

    En lower_smart una palabra se pasa a minúsculas salvo "I" (y sus contracciones), las siglas de dos
    letras o más en mayúsculas y las palabras capitalizadas que no empiezan frase (nombres propios).
    Una palabra empieza frase si es la primera o si la anterior termina en . ? o !.
    """
    case = text_case_of(style)
    shown, sentence_start = [], True
    for word in words:
        text = word["text"]
        shown.append(_apply_case(text, case, sentence_start, style))
        sentence_start = _ends_sentence(text)
    return shown


def _apply_case(text, case, sentence_start, style):
    """El caso se decide con los signos de la palabra y luego se quitan si strip_punctuation lo pide."""
    text = text.strip()
    if case == "upper":
        text = text.upper()
    elif case == "lower_smart":
        text = _lower_smart(text, sentence_start)
    if style["strip_punctuation"]:
        text = _strip_marks(text)
    return text


def _strip_marks(text):
    """Quita los signos de los extremos y los de dentro, salvo el apóstrofo entre letras («I'm», «don't»)."""
    return _INNER_MARKS.sub("", _EDGE_MARKS.sub("", text))


def _lower_smart(text, sentence_start):
    prefix, core, suffix = _EDGES.match(text).groups()
    if not core or not core[0].isalpha():
        return text
    if core == "I" or core.startswith(("I'", "I’")):
        return prefix + "I" + core[1:].lower() + suffix
    if core.isalpha() and core.isupper() and len(core) >= 2:
        return text
    if core[0].isupper() and not sentence_start:
        return text
    return prefix + core.lower() + suffix


def _ends_sentence(text):
    return text.rstrip(_CLOSING_MARKS).endswith(_SENTENCE_END)
