// Palabras: texto y énfasis por palabra. Guardar regenera el ASS con el estilo guardado, sin transcribir.
import { api } from "../api.js";
import { clock, el, messageOf, status } from "../dom.js";
import { track } from "../controls.js";

// Énfasis de tres estados: Auto (null, lo decide el motor), Sí (true) y No (false).
const EMPHASIS = [
  ["auto", "Auto"],
  ["yes", "Sí"],
  ["no", "No"],
];
const emphasisKey = (emph) => (emph === true ? "yes" : emph === false ? "no" : "auto");
const emphasisValue = (key) => (key === "yes" ? true : key === "no" ? false : null);

// host: el panel. flush() guarda antes el estilo pendiente. onSaved() se llama tras guardar.
export function mountWords(host, { id, flush, onSaved }) {
  let alive = true;
  let words = [];
  let original = "";
  let busy = false;

  const count = el("span", { class: "t-micro t-muted" });
  const stateLine = el("span", { "aria-live": "polite" });
  const saveButton = el("button", { type: "button", class: "cf-btn cf-btn--white cf-btn--32", disabled: true, onclick: save }, "Guardar palabras");
  const message = el("div", { "aria-live": "polite" });
  const list = el("div", { class: "words__list" });

  host.classList.add("words");
  host.setAttribute("aria-labelledby", "words-title");
  host.replaceChildren(
    el(
      "div",
      { class: "words__head" },
      el("h2", { class: "t-card words__title", id: "words-title", text: "Palabras" }),
      count,
      stateLine,
      saveButton,
    ),
    el("div", { class: "cf-groove", "aria-hidden": "true" }),
    message,
    list,
  );
  load();

  async function load() {
    try {
      words = await api.words(id);
      if (!alive) return;
      original = snapshot();
      render();
    } catch (error) {
      if (alive) say("danger", messageOf(error));
    }
  }

  function snapshot() {
    return JSON.stringify(words.map(({ text, start, end, emph }) => ({ text, start, end, emph })));
  }

  function say(tone, text) {
    message.replaceChildren(...(text ? [status(tone, text, "cf-status--ink")] : []));
  }

  function render() {
    list.replaceChildren(
      ...words.flatMap((word, index) => {
        const input = el("input", {
          type: "text",
          class: "cf-control words__text",
          value: word.text,
          maxlength: 60,
          spellcheck: "false",
          autocomplete: "off",
          "aria-label": `Texto de la palabra ${index + 1}`,
        });
        input.addEventListener("input", () => {
          word.text = input.value;
          refresh();
        });
        const label = el("span", { class: "sr-only", id: `emph-${index}`, text: `Énfasis de la palabra ${index + 1}` });
        const emphasis = track(EMPHASIS, `emph-${index}`, (key) => {
          word.emph = emphasisValue(key);
          emphasis.set(key);
          refresh();
        });
        emphasis.set(emphasisKey(word.emph));
        const row = el(
          "div",
          { class: "words__row", role: "group", "aria-label": `Palabra ${index + 1}` },
          el("span", { class: "words__time", text: clock(word.start) }),
          input,
          emphasis.node,
          label,
        );
        return index === 0 ? [row] : [el("div", { class: "cf-groove", "aria-hidden": "true" }), row];
      }),
    );
    count.textContent = `${words.length} palabras`;
    refresh();
  }

  // Botón y estado según lo que cambió. Una palabra vacía no se puede guardar.
  function refresh() {
    const dirty = snapshot() !== original;
    const empty = words.some((word) => !word.text.trim());
    saveButton.disabled = busy || !dirty || empty;
    if (empty) stateLine.replaceChildren(...statusNodes("danger", "Hay palabras vacías"));
    else if (dirty) stateLine.replaceChildren(...statusNodes("warning", "Cambios sin guardar"));
    else stateLine.replaceChildren();
  }

  function statusNodes(tone, text) {
    return [status(tone, text, "cf-status--ink")];
  }

  async function save() {
    if (busy) return;
    busy = true;
    saveButton.classList.add("is-saving");
    refresh();
    try {
      await flush();
      const payload = words.map(({ text, start, end, emph }) => ({ text: text.trim(), start, end, emph }));
      words = await api.saveWords(id, payload);
      if (!alive) return;
      original = snapshot();
      render();
      say("success", "Palabras guardadas. Los subtítulos ya usan el texto nuevo.");
      onSaved?.();
    } catch (error) {
      if (alive) say("danger", messageOf(error));
    } finally {
      busy = false;
      saveButton.classList.remove("is-saving");
      if (alive) refresh();
    }
  }

  return () => {
    alive = false;
  };
}
