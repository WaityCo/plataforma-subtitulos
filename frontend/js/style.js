// Campos del estilo: cómo se edita cada uno, en qué card vive y cuándo se muestra.
// Regla: un campo que el preset no usa no aparece fuera de Avanzado. Avanzado muestra el resto, y también los campos
// que el editor no conoce (defOf): con un control según su tipo, nunca se descartan.
import { hasBoldFace } from "./fonts.js";

export const MODES = [
  ["phrase", "Frase"],
  ["karaoke", "Karaoke"],
  ["karaoke_sweep", "Barrido"],
  ["karaoke_box", "Caja karaoke"],
  ["reveal", "Revelar"],
];
export const ANIMATIONS = [
  ["none", "Ninguna"],
  ["pop", "Pop"],
  ["fade", "Fundido"],
];
export const EMPHASES = [
  ["none", "Ninguno"],
  ["italic", "Cursiva"],
  ["color", "Color"],
  ["italic_color", "Cursiva y color"],
];
export const ENGINES = [
  ["length", "Longitud"],
  ["lexicon", "Léxico"],
];
export const SHADOWS = [
  ["hard", "Dura"],
  ["soft", "Suave"],
  ["halo", "Halo"],
];
export const TEXT_CASES = [
  ["as_is", "Tal cual"],
  ["upper", "Mayúsculas"],
  ["lower_smart", "Minúsculas inteligentes"],
];
export const TEXT_ALIGNS = [
  ["left", "Izquierda"],
  ["center", "Centro"],
];

export const italicOn = (style) => style.emphasis === "italic" || style.emphasis === "italic_color";
export const colorOn = (style) => style.emphasis === "color" || style.emphasis === "italic_color";
// Caso efectivo, como lo aplica el motor (text_case_of): uppercase es alias de upper y manda sobre text_case.
export const caseOf = (style) => (style.uppercase ? "upper" : style.text_case);

// Alineación numpad (1-9) a fila (bottom, mid, top) y columna (left, center, right), y su inversa.
const ROWS = ["bottom", "mid", "top"];
const COLS = ["left", "center", "right"];
export function placementOf(alignment) {
  return { row: ROWS[Math.floor((alignment - 1) / 3)], col: COLS[(alignment - 1) % 3] };
}
export function alignmentOf(row, col) {
  return 1 + ROWS.indexOf(row) * 3 + COLS.indexOf(col);
}

// Campos que solo cambian la pintura del overlay. Todo lo demás cambia lo que calcula el motor (posición, frases,
// anchos, énfasis, texto): además de aplicarse en pantalla, pide la vista previa de /segments.
const PAINT_ONLY = new Set([
  "text_color",
  "highlight_color",
  "outline_width",
  "outline_color",
  "shadow_style",
  "shadow_color",
  "shadow_opacity",
  "shadow_depth",
  "shadow_blur",
  "box_color",
  "box_opacity",
  "animation",
  "reveal_fade_ms",
  "highlight_box_color",
  "highlight_box_radius",
]);
export const needsLayout = (key) => !PAINT_ONLY.has(key);

// Cards del editor, en orden. tone es el pigmento del icon tile: el color nombra la categoría.
export const CARDS = [
  { id: "type", title: "Tipografía", icon: "type", tone: "1" },
  { id: "color", title: "Color", icon: "palette", tone: "5" },
  { id: "shadow", title: "Sombra", icon: "droplet", tone: "8" },
  { id: "position", title: "Posición", icon: "align", tone: "3" },
  { id: "rhythm", title: "Ritmo", icon: "clock", tone: "2" },
  { id: "emphasis", title: "Énfasis", icon: "wand", tone: "6" },
  { id: "advanced", title: "Avanzado", icon: "sliders", tone: "neutral" },
];

// Definición de cada campo. Tipos: toggle, number, percent (fracción mostrada en %), nullable (toggle + base),
// track (read y patch opcionales: el valor mostrado y los campos que van con él), select (nullable: opción que guarda
// null), color, align, text, words (lista de palabras) y raw (los campos que el editor no conoce). Las claves van en el
// orden en que aparecen dentro de su card.
export const FIELDS = {
  font_family: { kind: "select", label: "Familia", card: "type" },
  font_bold: { kind: "toggle", label: "Negrita", card: "type", show: (s, ctx) => ctx.hasBold(s.font_family) },
  font_size: { kind: "number", label: "Tamaño", min: 10, max: 300, step: 1, digits: 0, card: "type" },
  scale_x: { kind: "number", label: "Ancho de letra (%)", min: 10, max: 300, step: 1, digits: 0, card: "type" },
  scale_x_italic: {
    kind: "nullable",
    base: "number",
    label: "Ancho en cursiva (%)",
    min: 10,
    max: 300,
    step: 1,
    digits: 0,
    def: (s) => s.scale_x,
    off: "Igual que el ancho",
    card: "type",
    show: (s) => s.emphasis === "italic" || s.emphasis === "italic_color",
  },
  letter_spacing: { kind: "number", label: "Espacio entre letras", min: -50, max: 50, step: 0.25, digits: 2, card: "type" },
  word_space_scale: { kind: "number", label: "Espacio entre palabras (%)", min: 1, max: 300, step: 1, digits: 0, card: "type" },
  text_case: {
    kind: "track",
    label: "Caso del texto",
    options: "TEXT_CASES",
    card: "type",
    read: caseOf,
    patch: () => ({ uppercase: false }),
  },
  strip_punctuation: { kind: "toggle", label: "Quitar puntuación", card: "advanced" },
  uppercase: { kind: "toggle", label: "Mayúsculas (alias de upper)", card: "advanced" },
  exact_metrics: { kind: "toggle", label: "Métricas exactas, como libass", card: "advanced" },

  text_color: { kind: "color", label: "Texto", card: "color" },
  highlight_color: {
    kind: "color",
    label: "Resaltado",
    card: "color",
    show: (s) => s.mode !== "phrase" || colorOn(s),
  },
  outline_width: { kind: "number", label: "Grosor del contorno", min: 0, max: 30, step: 0.5, digits: 1, card: "color" },
  outline_color: {
    kind: "color",
    label: "Contorno",
    card: "color",
    show: (s) => s.outline_width > 0 && s.shadow_style !== "halo",
  },
  highlight_box_color: {
    kind: "nullable",
    base: "color",
    label: "Color de la caja",
    def: (s) => s.highlight_color,
    off: "Igual que el resaltado",
    card: "color",
    show: (s) => s.mode === "karaoke_box",
  },
  highlight_box_radius: {
    kind: "number",
    label: "Radio de la caja",
    min: 0,
    max: 100,
    step: 1,
    digits: 0,
    card: "color",
    show: (s) => s.mode === "karaoke_box",
  },
  highlight_box_padding_x: {
    kind: "number",
    label: "Relleno horizontal de la caja",
    min: 0,
    max: 100,
    step: 1,
    digits: 0,
    card: "color",
    show: (s) => s.mode === "karaoke_box",
  },
  highlight_box_padding_y: {
    kind: "number",
    label: "Relleno vertical de la caja",
    min: 0,
    max: 100,
    step: 1,
    digits: 0,
    card: "color",
    show: (s) => s.mode === "karaoke_box",
  },
  box_color: { kind: "nullable", base: "color", label: "Caja de fondo", def: () => "#000000", off: "Sin caja", card: "advanced" },
  box_opacity: { kind: "number", label: "Opacidad de la caja", min: 0, max: 1, step: 0.05, digits: 2, card: "advanced" },

  shadow_style: { kind: "track", label: "Estilo de sombra", options: "SHADOWS", card: "shadow" },
  shadow_color: { kind: "color", label: "Color de sombra", card: "shadow" },
  shadow_opacity: { kind: "number", label: "Opacidad", min: 0, max: 1, step: 0.01, digits: 2, card: "shadow" },
  shadow_depth: {
    kind: "number",
    label: "Distancia",
    min: 0,
    max: 20,
    step: 0.5,
    digits: 1,
    card: "shadow",
    show: (s) => s.shadow_style === "hard",
  },
  shadow_blur: {
    kind: "number",
    label: "Desenfoque",
    min: 0,
    max: 50,
    step: 0.5,
    digits: 1,
    card: "shadow",
    show: (s) => s.shadow_style !== "hard",
  },

  y_pct: {
    kind: "nullable",
    base: "percent",
    label: "Posición vertical",
    min: 0,
    max: 1,
    step: 0.005,
    digits: 3,
    def: () => 0.5,
    off: "Automática, según la alineación",
    card: "position",
  },
  alignment: { kind: "align", label: "Alineación", card: "position", show: (s) => s.y_pct == null },
  x_pct: {
    kind: "nullable",
    base: "percent",
    label: "Posición horizontal",
    min: 0,
    max: 1,
    step: 0.005,
    digits: 3,
    def: () => 0.5,
    off: "Centro del ancho",
    card: "position",
  },
  text_align: {
    kind: "track",
    label: "Alineación del texto",
    options: "TEXT_ALIGNS",
    card: "position",
    show: (s) => s.x_pct != null,
  },
  margin_v: { kind: "number", label: "Margen vertical", min: 0, max: 1920, step: 1, digits: 0, card: "advanced" },
  margin_h: { kind: "number", label: "Margen horizontal", min: 0, max: 1080, step: 1, digits: 0, card: "advanced" },

  mode: { kind: "track", label: "Modo", options: "MODES", card: "rhythm" },
  max_words_per_line: { kind: "number", label: "Palabras por frase", min: 1, max: 20, step: 1, digits: 0, card: "rhythm" },
  max_chars: {
    kind: "nullable",
    base: "number",
    label: "Caracteres por frase",
    min: 1,
    max: 200,
    step: 1,
    digits: 0,
    def: () => 24,
    off: "Sin límite de caracteres",
    card: "rhythm",
  },
  animation: { kind: "track", label: "Animación", options: "ANIMATIONS", card: "rhythm" },
  reveal_fade_ms: {
    kind: "number",
    label: "Fundido al aparecer (ms)",
    min: 0,
    max: 1000,
    step: 10,
    digits: 0,
    card: "rhythm",
    show: (s) => s.mode === "reveal",
  },
  blank_gap_s: {
    kind: "nullable",
    base: "number",
    label: "Pausa en blanco (s)",
    min: 0,
    max: 10,
    step: 0.05,
    digits: 2,
    def: () => 0.3,
    off: "Sin pausa: la frase sigue hasta la siguiente",
    card: "rhythm",
  },
  max_lines: { kind: "number", label: "Líneas máximas", min: 1, max: 3, step: 1, digits: 0, card: "advanced" },
  pause_split_s: { kind: "number", label: "Pausa para partir (s)", min: 0, max: 10, step: 0.05, digits: 2, card: "advanced" },
  pause_split_min_words: { kind: "number", label: "Palabras mínimas tras pausa", min: 1, max: 20, step: 1, digits: 0, card: "advanced" },
  merge_orphans: { kind: "toggle", label: "Unir palabras sueltas", card: "advanced" },
  punctuation_closes: { kind: "text", label: "Puntuación que cierra la frase", card: "advanced" },
  tail_s: { kind: "number", label: "Cola tras la última palabra (s)", min: 0, max: 5, step: 0.01, digits: 2, card: "advanced" },
  min_duration_s: { kind: "number", label: "Duración mínima (s)", min: 0, max: 5, step: 0.01, digits: 2, card: "advanced" },
  line_height: {
    kind: "nullable",
    base: "number",
    label: "Interlineado (× em)",
    min: 0.5,
    max: 3,
    step: 0.01,
    digits: 2,
    def: () => 1.2,
    off: "Automático, como libass",
    card: "advanced",
  },
  balance_lines: { kind: "toggle", label: "Líneas equilibradas", card: "advanced" },
  split_before_words: { kind: "words", label: "Cortar antes de estas palabras", card: "advanced" },
  target_words: {
    kind: "nullable",
    base: "number",
    label: "Palabras objetivo por frase",
    min: 1,
    max: 20,
    step: 1,
    digits: 0,
    def: () => 3,
    off: "Sin objetivo",
    card: "advanced",
  },
  soft_max_chars: {
    kind: "nullable",
    base: "number",
    label: "Tope blando de caracteres",
    min: 1,
    max: 200,
    step: 1,
    digits: 0,
    def: () => 30,
    off: "Sin tope blando",
    card: "advanced",
  },
  hang_max_chars: { kind: "number", label: "Palabra colgada (letras máx.)", min: 0, max: 10, step: 1, digits: 0, card: "advanced" },

  emphasis: { kind: "track", label: "Estilo de énfasis", options: "EMPHASES", card: "emphasis" },
  emphasis_font_family: {
    kind: "select",
    label: "Familia del énfasis",
    nullable: "Igual que el texto",
    card: "emphasis",
    show: (s) => s.emphasis !== "none",
  },
  emphasis_italic: { kind: "toggle", label: "Cursiva en el énfasis", card: "emphasis", show: (s) => italicOn(s) },
  emphasis_size_scale: {
    kind: "number",
    label: "Escala del énfasis (×)",
    min: 0.1,
    max: 5,
    step: 0.05,
    digits: 2,
    card: "emphasis",
    show: (s) => s.emphasis !== "none",
  },
  emphasis_engine: {
    kind: "track",
    label: "Motor de énfasis",
    options: "ENGINES",
    card: "emphasis",
    show: (s) => s.emphasis !== "none",
  },
  emphasis_ratio: {
    kind: "nullable",
    base: "percent",
    label: "Proporción de frases",
    min: 0,
    max: 1,
    step: 0.01,
    digits: 2,
    def: () => 0.3,
    off: "Todas las frases con puntaje",
    card: "emphasis",
    show: (s) => s.emphasis !== "none",
  },
  emphasis_auto: {
    kind: "toggle",
    label: "Énfasis automático",
    card: "emphasis",
    show: (s) => s.emphasis !== "none",
  },
  emphasis_letter_spacing: {
    kind: "nullable",
    base: "number",
    label: "Espacio entre letras del énfasis",
    min: -50,
    max: 50,
    step: 0.25,
    digits: 2,
    def: (s) => s.letter_spacing,
    off: "Igual que el texto",
    card: "advanced",
  },
  emphasis_max_per_segment: {
    kind: "nullable",
    base: "number",
    label: "Énfasis máximos por frase",
    min: 1,
    max: 20,
    step: 1,
    digits: 0,
    def: () => 2,
    off: "Sin límite",
    card: "advanced",
  },
};

const OPTIONS = { MODES, ANIMATIONS, EMPHASES, ENGINES, SHADOWS, TEXT_CASES, TEXT_ALIGNS };

// Opciones de un campo de tipo track (resuelve los nombres de arriba).
export function optionsOf(def) {
  return typeof def.options === "string" ? OPTIONS[def.options] : def.options;
}

// Definición de un campo que llega en el estilo pero no está en FIELDS. Control por tipo, en Avanzado: un booleano es
// un toggle; el resto, un texto (controls.js, rawField). Así un campo nuevo del motor se ve y no se pierde.
export function defOf(key, style) {
  if (FIELDS[key]) return FIELDS[key];
  if (typeof style[key] === "boolean") return { kind: "toggle", label: key, card: "advanced" };
  return { kind: "raw", label: key, card: "advanced" };
}

// Claves que se ven en una card. En Avanzado, las que no se ven en su card, las solo-avanzado y las que FIELDS no conoce.
export function fieldsFor(cardId, style, ctx) {
  const keys = [...Object.keys(FIELDS), ...Object.keys(style).filter((key) => !FIELDS[key])];
  return keys.filter((key) => {
    const def = defOf(key, style);
    const shown = def.card !== "advanced" && (def.show ? def.show(style, ctx) : true);
    return cardId === "advanced" ? !shown : def.card === cardId && shown;
  });
}

export const contextFor = () => ({ hasBold: hasBoldFace });

// Mismo valor que el preset (con tolerancia para decimales). Si es igual, no entra en overrides.
export function sameValue(a, b) {
  if (a === b) return true;
  if (a == null || b == null) return a == null && b == null;
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) < 1e-9;
  return false;
}

// Overrides mínimos: solo los campos que difieren del preset elegido.
export function withOverride(overrides, presetStyle, key, value) {
  const next = { ...overrides };
  if (sameValue(value, presetStyle[key])) delete next[key];
  else next[key] = value;
  return next;
}

export function resolveStyle(presetStyle, overrides) {
  return { ...presetStyle, ...overrides };
}
