// Overlay de subtítulos en SVG. Dibuja lo que calcula el motor en `layout` (px de referencia): cada palabra va en su
// x y en la línea de base de su línea, y las cajas de karaoke vienen ya medidas. El frontend no mide texto ni agrupa:
// el encaje es el del motor, y por eso coincide con el MP4 quemado.
//
// El viewBox sigue la proporción del video. El motor mide en un canvas de 1920 de alto y de ancho = ancho del video /
// (alto / 1920): para 9:16 es 1080 × 1920; para otras proporciones, el ancho cambia.
//
// Modos: phrase (todo visible), karaoke (palabra activa en resaltado), karaoke_sweep (barrido), karaoke_box (caja
// detrás de la palabra activa) y reveal (cada palabra aparece en su reveal_at con fundido). Para un modo nuevo:
// un caso en SubtitleOverlay.update() y, si pinta distinto, en buildView().
//
// El gancho de apertura va en su propia capa, encima de los subtítulos, y se ve desde 0 hasta duration_s.
import { advance, cssScale, hasBoldFace, metricsOf } from "./fonts.js";
import { clamp } from "./dom.js";
import { colorOn, italicOn } from "./style.js";

const NS = "http://www.w3.org/2000/svg";
export const REF_HEIGHT = 1920;
// Ancho del canvas de referencia del gancho (engine/hook.py, REFERENCE_WIDTH). Sus medidas se escalan por refWidth / 1080.
const HOOK_REF_WIDTH = 1080;
let seq = 0;

function node(tag, attrs = {}) {
  const element = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, String(value));
  return element;
}

export function rgba(hex, alpha) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

// Índice del segmento que cubre t, o -1. Los segmentos llegan ordenados por inicio.
export function findSegment(segments, t) {
  let low = 0;
  let high = segments.length - 1;
  let found = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (segments[mid].start <= t) {
      found = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return found >= 0 && t < segments[found].end ? found : -1;
}

// Avance de una ventana de barrido: 0 antes, 1 después, lineal dentro.
export function progressOf(timing, t) {
  const span = timing.end - timing.start;
  if (span <= 0) return t >= timing.start ? 1 : 0;
  return clamp((t - timing.start) / span, 0, 1);
}

// Palabra activa en las ventanas de karaoke, o -1.
function activeWordAt(segment, t) {
  const timing = segment.windows.find((item) => t >= item.start && t < item.end);
  return timing ? timing.index : -1;
}

// Contorno: en halo, el color de la sombra con su opacidad (así lo dibuja el ASS de Ken).
function outlineColorOf(style) {
  return style.shadow_style === "halo" ? rgba(style.shadow_color, style.shadow_opacity) : style.outline_color;
}

// Sombra como filtro SVG, en unidades de referencia. Hard: un desplazamiento sin desenfoque. Soft: un desenfoque
// sin desplazamiento. Halo: el text-shadow de Ken (0 1px 6px y 0 0 2px) con la opacidad del estilo.
function shadowFilter(id, style, refWidth) {
  const color = style.shadow_color;
  const alpha = style.shadow_opacity;
  const spread = style.shadow_blur / 2; // desviación estándar ≈ radio de desenfoque / 2
  let layers = [];
  if (style.shadow_style === "halo") {
    layers = [
      { dx: 0, dy: 1, sd: spread, a: alpha * 0.8 },
      { dx: 0, dy: 0, sd: 1, a: alpha * 0.45 },
    ];
  } else if (style.shadow_style === "soft") {
    layers = spread > 0 ? [{ dx: 0, dy: 0, sd: spread, a: alpha }] : [];
  } else if (style.shadow_depth > 0) {
    layers = [{ dx: style.shadow_depth, dy: style.shadow_depth, sd: 0, a: alpha }];
  }
  if (!layers.length) return null;
  const filter = node("filter", {
    id,
    filterUnits: "userSpaceOnUse",
    x: 0,
    y: 0,
    width: refWidth,
    height: REF_HEIGHT,
    "color-interpolation-filters": "sRGB",
  });
  layers.forEach((layer, i) =>
    filter.append(
      node("feDropShadow", {
        in: "SourceGraphic",
        dx: layer.dx,
        dy: layer.dy,
        stdDeviation: layer.sd,
        "flood-color": color,
        "flood-opacity": layer.a,
        result: `s${i}`,
      }),
    ),
  );
  const merge = node("feMerge");
  layers.forEach((_, i) => merge.append(node("feMergeNode", { in: `s${i}` })));
  merge.append(node("feMergeNode", { in: "SourceGraphic" }));
  filter.append(merge);
  return filter;
}

// Fuente de una palabra: la familia, cursiva y tamaño que trae el motor por palabra, con css_scale del catálogo.
// Ancho en X: scale_x, o scale_x_italic en cursiva. El espaciado va en unidades de referencia.
function glyphOf(style, word, k) {
  const family = word.family ?? style.font_family;
  const italic = word.italic ?? (italicOn(style) && !!word.emph);
  const bold = !!style.font_bold && hasBoldFace(family);
  const size = style.font_size * cssScale(family, bold, italic) * (word.size_scale ?? 1) * k;
  const scaleX = (italic ? (style.scale_x_italic ?? style.scale_x) : style.scale_x) / 100;
  const spacing = word.emph && style.emphasis_letter_spacing != null ? style.emphasis_letter_spacing : style.letter_spacing;
  return { family, bold, italic: !!italic, size, scaleX: Math.max(scaleX, 0.01), spacing };
}

function stop(offset, color) {
  return node("stop", { offset, "stop-color": color });
}

// Barrido: gradiente de la palabra con el resaltado a la izquierda y el texto a la derecha. Se mueve con p.
function sweepGradient(id, style) {
  const gradient = node("linearGradient", { id, x1: 0, x2: 1, y1: 0, y2: 0 });
  gradient.append(
    stop(0, style.highlight_color),
    stop(0, style.highlight_color),
    stop(0, style.text_color),
    stop(1, style.text_color),
  );
  return gradient;
}

// Cajas de BorderStyle 3 (libass): una por línea, con Outline (outline_width) de padding en cada lado. Con sombra dura,
// la caja se repite desplazada shadow_depth, con el mismo color y opacidad, por debajo de todas las cajas.
function lineBoxes(layout, style) {
  const group = node("g", { class: "subs__boxes" });
  if (style.box_color == null) return group;
  const pad = style.outline_width;
  const depth = style.shadow_style === "soft" || style.shadow_style === "halo" ? 0 : style.shadow_depth;
  const rects = layout.lines.map((line) => ({
    x: line.x - pad,
    y: line.baseline - line.ascent - pad,
    width: line.w + 2 * pad,
    height: line.ascent + line.descent + 2 * pad,
  }));
  const paint = { fill: style.box_color, "fill-opacity": style.box_opacity };
  if (depth > 0) for (const r of rects) group.append(node("rect", { ...r, x: r.x + depth, y: r.y + depth, ...paint }));
  for (const r of rects) group.append(node("rect", { ...r, ...paint }));
  return group;
}

// Lo que se ve de un segmento: caja (karaoke_box), contorno, relleno, sombra y gradientes de barrido.
function buildView(segment, style, refWidth) {
  const layout = segment.layout;
  const k = segment.fit / 100;
  const id = `seg${++seq}`;
  const meta = new Map(segment.lines.flat().map((word) => [word.index, word]));
  const timing = new Map(segment.windows.map((item) => [item.index, item]));
  const defs = node("defs");
  const group = node("g", { class: "subs__seg" });
  // Con box_color, libass dibuja cajas (BorderStyle 3) en vez de contorno, y la sombra es la de la caja (lineBoxes).
  const boxed = style.box_color != null;
  const outlined = !boxed && style.outline_width > 0;
  const filter = boxed ? null : shadowFilter(`${id}-shadow`, style, refWidth);
  if (filter) defs.append(filter);
  const box = node("rect", {
    class: "subs__box",
    rx: style.highlight_box_radius ?? 0,
    fill: style.highlight_box_color ?? "none",
    visibility: "hidden",
  });
  const outlineGroup = node("g", { class: "subs__outline" });
  const fillGroup = node("g", { class: "subs__fill" });
  if (filter) (outlined ? outlineGroup : fillGroup).setAttribute("filter", `url(#${id}-shadow)`);
  group.append(defs, lineBoxes(layout, style), box, outlineGroup, fillGroup);

  const words = new Map();
  for (const line of layout.lines) {
    for (const place of line.words) {
      const word = meta.get(place.index);
      if (!word || !word.display) continue;
      const glyph = glyphOf(style, word, k);
      const transform = `translate(${place.x}px, ${line.baseline}px) scale(${glyph.scaleX}, 1)`;
      const text = (layer) => {
        layer.textContent = word.display;
        Object.assign(layer.style, {
          transform,
          fontFamily: `"${glyph.family}"`,
          fontSize: `${glyph.size}px`,
          fontWeight: glyph.bold ? "700" : "400",
          fontStyle: glyph.italic ? "italic" : "normal",
          letterSpacing: `${glyph.spacing / glyph.scaleX}px`,
        });
        return layer;
      };
      const record = {
        word,
        x: place.x,
        y: line.baseline,
        scaleX: glyph.scaleX,
        box: place.box ?? null,
        timing: timing.get(place.index) ?? null,
        outline: null,
        fill: text(node("text", { x: 0, y: 0 })),
        gradient: null,
        p: null,
      };
      if (outlined) {
        const outline = text(node("text", { x: 0, y: 0 }));
        Object.assign(outline.style, {
          fill: outlineColorOf(style),
          stroke: outlineColorOf(style),
          strokeWidth: `${2 * style.outline_width}px`,
          paintOrder: "stroke",
          strokeLinejoin: "round",
        });
        outlineGroup.append(outline);
        record.outline = outline;
      }
      if (style.mode === "karaoke_sweep" && record.timing && !(colorOn(style) && word.emph)) {
        record.gradient = sweepGradient(`${id}-g${place.index}`, style);
        defs.append(record.gradient);
      }
      fillGroup.append(record.fill);
      words.set(place.index, record);
    }
  }
  return { id, segment, group, box, words, active: undefined, anchor: layout.anchor };
}

// Color de relleno de una palabra según el modo y la palabra activa.
function applyFill(record, style, active) {
  const { word } = record;
  if (style.mode === "karaoke" && word.index === active) record.fill.style.fill = style.highlight_color;
  else if (colorOn(style) && word.emph) record.fill.style.fill = style.highlight_color;
  else if (record.gradient) record.fill.style.fill = `url(#${record.gradient.id})`;
  else record.fill.style.fill = style.text_color;
}

// Caja de karaoke_box detrás de la palabra activa, con la geometría que trae el motor.
function placeBox(view, style, active) {
  const record = active >= 0 ? view.words.get(active) : null;
  if (!record?.box) {
    view.box.setAttribute("visibility", "hidden");
    return;
  }
  view.box.setAttribute("x", record.box.x);
  view.box.setAttribute("y", record.box.y);
  view.box.setAttribute("width", record.box.w);
  view.box.setAttribute("height", record.box.h);
  view.box.setAttribute("rx", style.highlight_box_radius ?? 0);
  view.box.setAttribute("fill", style.highlight_box_color ?? "none");
  view.box.setAttribute("visibility", "visible");
}

// Pulso de la palabra activa en karaoke: 112 % en 90 ms y de vuelta en 90 ms, desde su línea de base.
function popWord(record) {
  const frame = (p) => ({ transform: `translate(${record.x}px, ${record.y}px) scale(${record.scaleX * p}, ${p})` });
  const frames = [frame(1), { ...frame(1.12), offset: 0.5 }, frame(1)];
  for (const layer of [record.fill, record.outline]) layer?.animate(frames, { duration: 180, easing: "linear" });
}

// Entrada de la frase: pop (112 % y vuelta en 220 ms) o fundido de 80 ms, desde el ancla del motor.
function enter(group, anchor, animation) {
  group.style.transformBox = "view-box";
  group.style.transformOrigin = `${anchor.x}px ${anchor.y}px`;
  if (animation === "pop") {
    group.animate([{ transform: "scale(1)" }, { transform: "scale(1.12)", offset: 0.5 }, { transform: "scale(1)" }], {
      duration: 220,
      easing: "linear",
    });
  } else if (animation === "fade") {
    group.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 80 });
  }
}

// Gancho de apertura (engine/hook.py): píldora blanca con el titular, kicker encima y rótulos de noticiero. Las medidas
// de Pillow son de un canvas de 1080 de ancho: aquí se pasan a unidades del viewBox con s = refWidth / 1080. El corte del
// titular en líneas lo hace la fuente de la app, así que puede diferir de Pillow en el límite de una línea.
const HOOK = {
  pillWidth: 0.87, // fracción del ancho del video
  pillTop: 0.43, // fracción del alto del video
  pillRadius: 20,
  headlinePx: 59,
  kickerGap: 22,
  newsTilt: -3, // como rotate(-3deg) de CSS: el borde derecho sube
  red: "#D7191C",
  blue: "#1E63E9",
};
const MEDIUM = "Montserrat Medium";
const BOLD = "Montserrat";

// Líneas de un texto que caben en maxWidth, con la fuente y el tamaño dados (unidades del viewBox).
function wrapText(text, family, bold, px, maxWidth) {
  const space = advance(" ", family, bold, false, px);
  const lines = [];
  let current = [];
  let width = 0;
  for (const word of text.trim().split(/\s+/)) {
    const wordWidth = advance(word, family, bold, false, px);
    if (current.length && width + space + wordWidth > maxWidth) {
      lines.push(current.join(" "));
      current = [word];
      width = wordWidth;
    } else {
      width += current.length ? space + wordWidth : wordWidth;
      current.push(word);
    }
  }
  if (current.length) lines.push(current.join(" "));
  return lines;
}

function svgText(content, attrs) {
  const element = node("text", attrs);
  element.textContent = content;
  return element;
}

// Rótulo de color con texto blanco. Con tilt, la barra gira alrededor de su centro, y (x, y) es la esquina superior
// izquierda de la imagen ya girada, como en Pillow con expand=True.
function newsBar(label, { x, y, color, family, bold, px, tilt }, s) {
  const padX = 16 * s;
  const padY = 10 * s;
  const metrics = metricsOf(family, bold, false, px);
  const width = advance(label, family, bold, false, px) + 2 * padX;
  const height = metrics.ascent + metrics.descent + 2 * padY;
  const radians = (Math.abs(tilt) * Math.PI) / 180;
  const boxWidth = width * Math.cos(radians) + height * Math.sin(radians);
  const boxHeight = width * Math.sin(radians) + height * Math.cos(radians);
  const cx = x + boxWidth / 2;
  const cy = y + boxHeight / 2;
  const left = cx - width / 2;
  const top = cy - height / 2;
  const group = node("g", tilt ? { transform: `rotate(${tilt} ${cx} ${cy})` } : {});
  group.append(
    node("rect", { x: left, y: top, width, height, fill: color }),
    svgText(label, {
      x: left + padX,
      y: top + padY + metrics.ascent,
      fill: "#FFFFFF",
      "font-family": `"${family}"`,
      "font-size": px,
      "font-weight": bold ? 700 : 400,
    }),
  );
  return group;
}

// Píldora, kicker y rótulos del gancho en unidades del viewBox. Se construye al cambiar el gancho; show() decide cuándo
// se ve.
function buildHook(spec, refWidth) {
  const s = refWidth / HOOK_REF_WIDTH;
  const group = node("g", { class: "subs__hook" });
  const pillWidth = HOOK.pillWidth * refWidth;
  const left = (refWidth - pillWidth) / 2;
  const top = HOOK.pillTop * REF_HEIGHT;
  const center = left + pillWidth / 2;
  const padX = 28 * s;
  const padY = 12 * s;

  // Hasta dos líneas: si no caben, la fuente baja de 2 px de referencia en 2 px, hasta 40 px, como hook.py.
  let px = HOOK.headlinePx * s;
  let lines = wrapText(spec.headline, MEDIUM, false, px, pillWidth - 2 * padX);
  while (lines.length > 2 && px > 40 * s) {
    px -= 2 * s;
    lines = wrapText(spec.headline, MEDIUM, false, px, pillWidth - 2 * padX);
  }
  const metrics = metricsOf(MEDIUM, false, false, px);
  const lineHeight = (metrics.ascent + metrics.descent) * 1.1;
  group.append(
    node("rect", {
      x: left,
      y: top,
      width: pillWidth,
      height: 2 * padY + lineHeight * lines.length,
      rx: HOOK.pillRadius * s,
      fill: "#FFFFFF",
    }),
  );
  lines.forEach((line, index) =>
    group.append(
      svgText(line, {
        x: center,
        y: top + padY + metrics.ascent + index * lineHeight,
        "text-anchor": "middle",
        fill: "#000000",
        "font-family": `"${MEDIUM}"`,
        "font-size": px,
      }),
    ),
  );

  if (spec.kicker) {
    const kicker = metricsOf(MEDIUM, false, false, HOOK.headlinePx * s);
    const kickerTop = top - (kicker.ascent + kicker.descent + 4 * s) - HOOK.kickerGap * s;
    group.append(
      svgText(spec.kicker, {
        x: center,
        y: kickerTop + kicker.ascent + 2 * s,
        "text-anchor": "middle",
        fill: "#FFFFFF",
        "font-family": `"${MEDIUM}"`,
        "font-size": HOOK.headlinePx * s,
      }),
    );
  }
  if (spec.news_title) {
    group.append(
      newsBar(
        spec.news_title.toUpperCase(),
        { x: 0.01 * refWidth, y: 0.855 * REF_HEIGHT, color: HOOK.red, family: BOLD, bold: true, px: 44 * s, tilt: HOOK.newsTilt },
        s,
      ),
    );
  }
  if (spec.news_subtitle) {
    group.append(
      newsBar(
        spec.news_subtitle,
        { x: 0.13 * refWidth, y: 0.9 * REF_HEIGHT, color: HOOK.blue, family: MEDIUM, bold: false, px: 40 * s, tilt: 0 },
        s,
      ),
    );
  }
  return group;
}

// Overlay de un video. El estado sale del tiempo t: cambiar de segmento dibuja y anima la entrada; el resto de
// cambios (palabra activa, barrido, reveal) se aplica sobre lo ya dibujado. video: { width, height } del job.
export class SubtitleOverlay {
  constructor(frame, video) {
    this.frame = frame;
    this.refWidth = (video.width * REF_HEIGHT) / video.height;
    this.root = node("svg", {
      class: "subs",
      viewBox: `0 0 ${this.refWidth} ${REF_HEIGHT}`,
      preserveAspectRatio: "xMidYMid meet",
      "aria-hidden": "true",
      focusable: "false",
    });
    this.layer = node("g");
    this.hookLayer = node("g");
    this.root.append(this.layer, this.hookLayer);
    frame.append(this.root);
    this.style = null;
    this.hook = null;
    this.segments = [];
    this.time = 0;
    this.current = -1;
    this.view = null;
  }

  setStyle(style) {
    this.style = style;
    this.show(this.time, { force: true });
  }

  setSegments(segments) {
    this.segments = segments;
    this.show(this.time, { force: true });
  }

  // Gancho de apertura, o null para quitarlo. Se dibuja aquí y se ve desde 0 hasta duration_s.
  setHook(spec) {
    this.hook = spec;
    this.hookLayer.replaceChildren(...(spec ? [buildHook(spec, this.refWidth)] : []));
    this.paintHook(this.time);
  }

  paintHook(t) {
    const visible = !!this.hook && t >= 0 && t < this.hook.duration_s;
    this.hookLayer.setAttribute("display", visible ? "inline" : "none");
  }

  // force redibuja sin animar: cambios de estilo o de segmentos.
  show(t, { force = false } = {}) {
    this.time = t;
    this.paintHook(t);
    if (!this.style) return;
    const index = findSegment(this.segments, t);
    if (force || index !== this.current) this.build(index, { animate: !force });
    else if (this.view) this.update(t);
  }

  build(index, { animate }) {
    this.current = index;
    this.layer.replaceChildren();
    this.view = null;
    if (index < 0 || !this.segments[index].layout) return;
    this.view = buildView(this.segments[index], this.style, this.refWidth);
    this.layer.append(this.view.group);
    if (animate) enter(this.view.group, this.view.anchor, this.style.animation);
    this.update(this.time);
  }

  // Un caso por modo. Para añadir uno: su rama aquí.
  update(t) {
    const { style, view } = this;
    const active = style.mode === "karaoke" || style.mode === "karaoke_box" ? activeWordAt(view.segment, t) : -1;
    if (!view.painted || active !== view.active) {
      view.painted = true;
      view.active = active;
      for (const record of view.words.values()) applyFill(record, style, active);
      if (style.mode === "karaoke_box") placeBox(view, style, active);
      else if (style.mode === "karaoke" && style.animation === "pop" && active >= 0) popWord(view.words.get(active));
    }
    for (const record of view.words.values()) {
      if (record.gradient && record.timing) {
        const p = progressOf(record.timing, t);
        if (p !== record.p) {
          record.p = p;
          const [, middle, after] = record.gradient.children;
          middle.setAttribute("offset", p);
          after.setAttribute("offset", p);
        }
      }
      if (style.mode === "reveal" && record.word.reveal_at != null) {
        const fade = (style.reveal_fade_ms ?? 0) / 1000;
        const alpha = fade > 0 ? clamp((t - record.word.reveal_at) / fade, 0, 1) : t >= record.word.reveal_at ? 1 : 0;
        record.fill.style.opacity = alpha;
        if (record.outline) record.outline.style.opacity = alpha;
      }
    }
  }
}
