// Helpers de DOM sin dependencias. Los textos entran siempre como textContent; el HTML solo sale de icons.js.
import { icon } from "./icons.js";

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "style") Object.assign(node.style, value);
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child);
  }
  return node;
}

export function ico(name) {
  const node = el("span", { "data-icon": name, "aria-hidden": "true" });
  node.innerHTML = icon(name);
  return node;
}

// Punto de estado más texto (regla del DS). tone: success, warning, danger, info o vacío (neutro).
export function status(tone, text, extraClass = "") {
  const node = el("span", { class: `cf-status ${extraClass}`.trim() });
  setStatus(node, tone, text);
  return node;
}

export function setStatus(node, tone, text) {
  node.replaceChildren(
    el("span", { class: tone ? `cf-dot cf-dot--${tone}` : "cf-dot" }),
    el("span", { text }),
  );
}

// Barra de ticks de 100: los primeros `filled` toman el pigmento de la etapa (data-1 por defecto).
export function ticksBar(count = 100, pigment = 1) {
  const bar = el("div", { class: "cf-ticks", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": 0 });
  bar.append(...Array.from({ length: count }, () => el("span", { class: "cf-tick" })));
  bar.dataset.pigment = String(pigment);
  return bar;
}

export function setTicks(bar, filled) {
  const pigment = bar.dataset.pigment || "1";
  const ticks = bar.children;
  const count = Math.round(clamp(filled, 0, ticks.length));
  for (let i = 0; i < ticks.length; i++) {
    const on = i < count;
    const want = on ? `cf-tick is-${pigment}` : "cf-tick";
    if (ticks[i].className !== want) ticks[i].className = want;
  }
  bar.setAttribute("aria-valuenow", String(Math.round((count / ticks.length) * 100)));
}

export function debounce(fn, ms) {
  let timer = 0;
  const call = (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
  call.cancel = () => clearTimeout(timer);
  return call;
}

export const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

export function roundTo(value, digits) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

// 1.5 -> "1.50"; sin decimales, "24". Para campos numéricos.
export function fixed(value, digits) {
  return digits > 0 ? value.toFixed(digits) : String(Math.round(value));
}

// Segundos -> "00:01.25", el formato de la lista de palabras.
export function clock(seconds) {
  const minutes = Math.floor(seconds / 60);
  const rest = (seconds - minutes * 60).toFixed(2).padStart(5, "0");
  return `${String(minutes).padStart(2, "0")}:${rest}`;
}

export function megabytes(bytes) {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function fileLabel(name) {
  return name.length > 48 ? `${name.slice(0, 45)}…` : name;
}

// Mensaje legible de un error de la API o de la red.
export function messageOf(error) {
  return error?.detail || error?.message || "Algo salió mal.";
}
