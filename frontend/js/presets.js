// Grid de presets. Cada tarjeta muestra la miniatura real del backend (un cuadro del video con el subtítulo ya
// quemado por libass) cuando el job tiene una. Mientras carga, la media se queda con la pista de ticks vacía. Si no
// hay job o el backend no tiene el endpoint, la media es una muestra CSS aproximada del preset.
import { api, ApiError } from "./api.js";
import { el, ticksBar } from "./dom.js";
import { cssScale, hasBoldFace } from "./fonts.js";
import { colorOn, italicOn } from "./style.js";

const THUMB_WIDTH = 360;
const frames = new Map(); // "job|preset|w" -> promesa de { src, time }
const unavailable = new Map(); // job -> error (404, 500 o 501): el backend no da cuadros y no se vuelve a pedir
const queue = [];
let running = 0;

// Dos descargas a la vez: cada miniatura es un ffmpeg, no conviene lanzar once juntas.
function enqueue(task) {
  return new Promise((resolve, reject) => {
    queue.push({ task, resolve, reject });
    pump();
  });
}

function pump() {
  while (running < 2 && queue.length) {
    const { task, resolve, reject } = queue.shift();
    running += 1;
    task()
      .then(resolve, reject)
      .finally(() => {
        running -= 1;
        pump();
      });
  }
}

// Miniatura de un preset en un ancho dado. Se cachea por job, preset y ancho.
export function thumbnail(jobId, presetId, width = THUMB_WIDTH) {
  const key = `${jobId}|${presetId}|${width}`;
  if (!frames.has(key)) {
    const pending = enqueue(() => api.previewFrame(jobId, presetId, width));
    frames.set(key, pending);
    pending.catch(() => frames.delete(key));
  }
  return frames.get(key);
}

// Muestra CSS aproximada: dos palabras con la familia, color, sombra y énfasis del preset. Es solo orientativa;
// la verdad es la miniatura real. El tamaño sale del tamaño del contenedor (cqh).
export function sampleNode(preset) {
  const style = preset.style;
  const family = style.font_family;
  const bold = !!style.font_bold && hasBoldFace(family);
  const scale = (style.font_size * cssScale(family, false, false)) / 93.6; // 93.6 = Ken Remedie, referencia de tamaño
  const size = Math.max(14, 30 * scale);
  const shadow =
    style.shadow_style === "hard"
      ? `${style.shadow_depth * 0.04}em ${style.shadow_depth * 0.04}em 0 rgba(0, 0, 0, ${style.shadow_opacity})`
      : `0 0 0.18em rgba(0, 0, 0, ${style.shadow_opacity})`;
  const words = ["Dormir", "mejor"].map((text, index) => {
    const span = el("span", { class: "preset-sample__word", text: style.uppercase ? text.toUpperCase() : text });
    const emphasized = index === 1;
    if (emphasized && (italicOn(style) || colorOn(style))) span.style.fontStyle = italicOn(style) ? "italic" : "normal";
    if (emphasized && colorOn(style)) span.style.color = style.highlight_color;
    if (emphasized && style.mode === "karaoke") span.style.color = style.highlight_color;
    if (emphasized && style.mode === "karaoke_sweep") {
      span.style.backgroundImage = `linear-gradient(90deg, ${style.highlight_color} 50%, ${style.text_color} 50%)`;
      span.style.webkitBackgroundClip = "text";
      span.style.backgroundClip = "text";
      span.style.color = "transparent";
    }
    if (emphasized && style.mode === "karaoke_box") {
      span.style.background = style.highlight_box_color ?? style.highlight_color;
      span.style.borderRadius = `${(style.highlight_box_radius ?? 0) * 0.04}em`;
      span.style.padding = "0 0.12em";
    }
    return span;
  });
  return el(
    "span",
    {
      class: "preset-sample",
      style: {
        fontFamily: `"${family}"`,
        fontSize: `min(${size}cqh, 13cqw)`,
        fontWeight: bold ? "700" : "400",
        color: style.text_color,
        textShadow: shadow,
        WebkitTextStroke: style.outline_width > 0 ? `${style.outline_width * 0.01}em ${style.outline_color}` : "0",
      },
    },
    words[0],
    " ",
    words[1],
  );
}

// Tarjeta de preset: media (miniatura o muestra), nombre, una línea de descripción y el chip de selección.
function presetCard(preset, opts, grid) {
  const media = el("span", { class: "preset-card__media", "data-preset": preset.id });
  media.append(el("span", { class: "preset-card__empty" }, ticksBar(40, 1)));
  const chip = el("span", { class: "cf-chip cf-chip--ink", text: opts.chip, hidden: true });
  const head = el(
    "span",
    { class: "preset-card__head" },
    el("span", { class: "t-card preset-card__name", text: preset.label }),
    chip,
  );
  const body = el(
    "span",
    { class: "preset-card__body" },
    head,
    el("span", { class: "t-micro t-muted preset-card__desc", text: preset.description }),
  );
  const interactive = opts.onPick ? { type: "button", "aria-pressed": "false" } : {};
  const card = el(opts.onPick ? "button" : "span", { class: "preset-card", "data-preset": preset.id, ...interactive }, media, body);
  if (opts.onPick) card.addEventListener("click", () => opts.onPick(preset.id));
  if (opts.onEnter) {
    card.addEventListener("mouseenter", () => opts.onEnter(preset.id, media.dataset.time));
    card.addEventListener("focus", () => opts.onEnter(preset.id, media.dataset.time));
  }
  if (opts.onLeave) {
    card.addEventListener("mouseleave", () => opts.onLeave(preset.id));
    card.addEventListener("blur", () => opts.onLeave(preset.id));
  }
  grid.cards.set(preset.id, { card, media, chip, preset });
  return card;
}

// Nota de la rejilla cuando el backend no da los cuadros exactos (500 o 501): lleva el detail tal cual. Null en otro caso.
export function unavailableNote(error) {
  return error && (error.status === 500 || error.status === 501) && error.detail
    ? `Las miniaturas exactas no están disponibles: ${error.detail}`
    : null;
}

// Carga la media de la tarjeta: miniatura del job o, si no hay, la muestra CSS.
async function fillMedia(entry, job, onMode) {
  const { media, preset } = entry;
  if (!job) {
    onMode?.("samples");
    return showSample(media, preset);
  }
  if (unavailable.has(job.id)) {
    onMode?.("samples", unavailable.get(job.id));
    return showSample(media, preset);
  }
  try {
    const frame = await thumbnail(job.id, preset.id);
    const image = el("img", { class: "preset-card__img", src: frame.src, alt: `Cuadro del video con el preset ${preset.label}`, decoding: "async" });
    if (frame.time != null) media.dataset.time = String(frame.time);
    media.replaceChildren(image);
    onMode?.("frames");
  } catch (error) {
    if (error instanceof ApiError && [404, 500, 501].includes(error.status)) unavailable.set(job.id, error);
    onMode?.("samples", error);
    showSample(media, preset);
  }
}

function showSample(media, preset) {
  media.replaceChildren(el("span", { class: "preset-card__stage" }, sampleNode(preset)));
}

// Grid de presets. opts: presets, selectedId, job (o null para muestras CSS), compact, chip, onPick, onEnter,
// onLeave, onMode("frames" | "samples"): avisa si la media es un cuadro real o una muestra CSS. Devuelve el nodo, setSelected(id) y dispose().
export function presetGrid(opts) {
  const grid = el("div", {
    class: `preset-grid${opts.compact ? " preset-grid--compact" : ""}${opts.columns ? ` preset-grid--cols-${opts.columns}` : ""}`,
    role: "group",
    "aria-label": opts.label ?? "Presets",
  });
  grid.cards = new Map();
  const cardOpts = { chip: opts.chip ?? "Seleccionado", onPick: opts.onPick, onEnter: opts.onEnter, onLeave: opts.onLeave };
  for (const preset of opts.presets) grid.append(presetCard(preset, cardOpts, grid));

  const load = (entry) => {
    entry.loading = true;
    fillMedia(entry, opts.job ?? null, opts.onMode);
  };
  const observer =
    typeof IntersectionObserver === "function"
      ? new IntersectionObserver(
          (entries) => {
            for (const entry of entries) {
              if (!entry.isIntersecting) continue;
              observer.unobserve(entry.target);
              const item = grid.cards.get(entry.target.dataset.preset);
              if (item && !item.loading) load(item);
            }
          },
          { rootMargin: "240px 0px" },
        )
      : null;
  for (const entry of grid.cards.values()) {
    if (observer) observer.observe(entry.card);
    else load(entry);
  }

  const setSelected = (id) => {
    for (const [presetId, entry] of grid.cards) {
      const selected = presetId === id;
      entry.chip.hidden = !selected;
      entry.card.classList.toggle("is-selected", selected);
      if (entry.card.tagName === "BUTTON") entry.card.setAttribute("aria-pressed", String(selected));
    }
  };
  setSelected(opts.selectedId);
  return {
    node: grid,
    setSelected,
    dispose: () => observer?.disconnect(),
  };
}
