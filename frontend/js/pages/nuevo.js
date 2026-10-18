// Nuevo video: subida con progreso de subida y de transcripción. Cuando el job queda listo, abre el editor.
// Antes de subir, el preset se elige sobre muestras CSS aproximadas: la miniatura real aparece en el editor.
import { api, createJob } from "../api.js";
import { el, fileLabel, ico, megabytes, messageOf, setStatus, setTicks, status, ticksBar } from "../dom.js";
import { track } from "../controls.js";
import { presetGrid } from "../presets.js";
import { STATUS, defaultPresetId, rememberJob } from "../recents.js";
import { refreshRecent } from "../shell.js";

// Límite de subida: lo da /api/config (max_upload_bytes). Hasta que responde, no hay cifra ni se comprueba el tamaño.
let maxBytes = null;
const FORMAT = /\.(mp4|mov|webm)$/i;
const LANGUAGES = [
  ["", "Auto"],
  ["es", "ES"],
  ["en", "EN"],
];
const STAGES = { audio: "Extrayendo el audio", transcribe: "Transcribiendo el audio", subtitles: "Generando subtítulos" };
const DROP_TITLE = "Arrastra un video aquí o elígelo desde tu equipo";
const hintFor = (bytes) => (bytes ? `mp4, mov o webm, hasta ${Math.round(bytes / (1024 * 1024))} MB` : "mp4, mov o webm");

export function mountNuevo(view, ctx) {
  let alive = true;
  let timer = 0;
  let file = null;
  let language = "";
  let presetId = defaultPresetId(ctx.presets);
  let busy = false;

  const title = el("h1", { class: "t-page", tabindex: "-1", text: "Nuevo video" });
  const intro = el("p", {
    class: "t-body t-muted",
    text: "Sube un video vertical. Se transcribe una sola vez y después ajustas el estilo sin volver a transcribir.",
  });

  // Dropzone: clic en el botón o arrastrar el archivo. El input va oculto y solo lo abre el botón.
  const dropTitle = el("p", { class: "cf-dropzone__title", text: DROP_TITLE });
  const dropHint = el("p", { class: "cf-dropzone__hint", text: hintFor(maxBytes) });
  const fileInput = el("input", {
    type: "file",
    class: "sr-only",
    tabindex: "-1",
    accept: ".mp4,.mov,.webm,video/mp4,video/quicktime,video/webm",
  });
  const pick = el("button", { type: "button", class: "cf-btn cf-btn--white", onclick: () => fileInput.click() }, "Elegir archivo");
  const dropzone = el(
    "div",
    { class: "cf-dropzone", id: "dropzone" },
    el("span", { class: "cf-tile cf-tile--1" }, ico("upload")),
    dropTitle,
    dropHint,
    pick,
    fileInput,
  );

  // Idioma: track de tres opciones.
  const langLabel = el("span", { class: "cf-field__label", id: "nuevo-lang", text: "Idioma del audio" });
  const langTrack = track(LANGUAGES, "nuevo-lang", (value) => {
    language = value;
    langTrack.set(value);
  });
  langTrack.set("");

  // Preset inicial: muestras CSS sobre fondo neutro, con la etiqueta de vista aproximada.
  const presetPicker = presetGrid({
    presets: ctx.presets,
    selectedId: presetId,
    job: null,
    compact: true,
    label: "Preset inicial",
    chip: "Seleccionado",
    onPick: (id) => {
      presetId = id;
      presetPicker.setSelected(id);
    },
  });

  const start = el(
    "button",
    { type: "button", class: "cf-btn cf-btn--ink cf-btn--40", disabled: true, onclick: upload },
    "Subir y transcribir",
  );
  const message = el("div", { class: "form__msg", "aria-live": "polite" });

  const form = el(
    "section",
    { class: "cf-card pad-20", "aria-labelledby": "nuevo-form-title" },
    el("h2", { class: "sr-only", id: "nuevo-form-title", text: "Subir video" }),
    el(
      "div",
      { class: "nuevo__grid" },
      dropzone,
      el(
        "div",
        { class: "nuevo__side" },
        el("div", { class: "cf-field" }, el("div", { class: "cf-field__head" }, langLabel), langTrack.node),
        el("div", { class: "nuevo__actions" }, start),
      ),
    ),
    el(
      "div",
      { class: "nuevo__presets" },
      el("div", { class: "nuevo__presets-head" }, el("span", { class: "cf-field__label", id: "nuevo-preset-label", text: "Preset inicial" }), el("span", { class: "cf-chip cf-chip--outline", text: "Vista previa aproximada" })),
      el("p", { class: "cf-field__hint", text: "La miniatura real del video aparece en el editor, cuando la transcripción termina." }),
      presetPicker.node,
    ),
    message,
  );

  // Progreso: una sola barra de ticks para la subida y para la transcripción, con el estado en punto más texto.
  const bar = ticksBar(100, 1);
  bar.setAttribute("aria-labelledby", "nuevo-progress-title");
  const stateNode = status(null, "");
  stateNode.setAttribute("aria-live", "polite");
  const detail = el("p", { class: "t-micro t-muted progress__detail" });
  const progress = el(
    "section",
    { class: "cf-card pad-20", hidden: true, "aria-labelledby": "nuevo-progress-title" },
    el("div", { class: "progress__head" }, el("h2", { class: "t-card", id: "nuevo-progress-title", text: "Progreso" }), stateNode),
    bar,
    detail,
  );

  view.replaceChildren(el("header", { class: "page-head" }, title, intro), el("div", { class: "stack" }, form, progress));
  title.focus({ preventScroll: true });

  // Límite de subida del backend: GET /api/config, campo max_upload_bytes. Sin respuesta, no hay cifra.
  api
    .config()
    .then((config) => {
      if (!Number.isFinite(config?.max_upload_bytes)) return;
      maxBytes = config.max_upload_bytes;
      if (!file) dropHint.textContent = hintFor(maxBytes);
    })
    .catch(() => {});

  dropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropzone.classList.add("is-over");
  });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("is-over"));
  dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropzone.classList.remove("is-over");
    const next = event.dataTransfer?.files?.[0];
    if (next) choose(next);
  });
  fileInput.addEventListener("change", () => {
    const next = fileInput.files[0];
    fileInput.value = "";
    if (next) choose(next);
  });

  function say(tone, text) {
    message.replaceChildren(...(text ? [status(tone, text, "cf-status--ink")] : []));
  }

  function setBusy(on) {
    pick.disabled = on;
    start.disabled = on || !file;
    langTrack.node.querySelectorAll("button").forEach((chip) => {
      chip.disabled = on;
    });
    presetPicker.node.querySelectorAll("button").forEach((card) => {
      card.disabled = on;
    });
  }

  function choose(next) {
    if (busy) return;
    const problem = !FORMAT.test(next.name)
      ? "Formato no admitido: usa mp4, mov o webm."
      : maxBytes !== null && next.size > maxBytes
        ? `El archivo supera ${Math.round(maxBytes / (1024 * 1024))} MB.`
        : "";
    if (problem) {
      file = null;
      start.disabled = true;
      dropTitle.textContent = DROP_TITLE;
      dropHint.textContent = hintFor(maxBytes);
      say("danger", problem);
      return;
    }
    file = next;
    dropTitle.textContent = fileLabel(next.name);
    dropHint.textContent = `${megabytes(next.size)} · listo para subir`;
    start.disabled = false;
    say(null, "");
  }

  async function upload() {
    if (!file || busy) return;
    const name = file.name;
    busy = true;
    setBusy(true);
    say(null, "");
    progress.hidden = false;
    setStatus(stateNode, "info", "Subiendo video");
    setTicks(bar, 0);
    detail.textContent = "";
    try {
      const { job_id: id } = await createJob({ file, preset: presetId, language }, (fraction) => {
        if (!alive) return;
        setTicks(bar, fraction * 100);
        detail.textContent = `Subiendo: ${Math.round(fraction * 100)} %`;
      });
      rememberJob(id, name);
      refreshRecent();
      follow(id);
    } catch (error) {
      busy = false;
      setBusy(false);
      progress.hidden = true;
      say("danger", messageOf(error));
    }
  }

  // Sigue el job hasta ready: entonces abre el editor. Un error de red no corta el seguimiento.
  async function follow(id) {
    if (!alive) return;
    try {
      const job = await api.job(id);
      if (!alive) return;
      if (job.status === "ready" || job.status === "done" || job.status === "rendering") {
        location.hash = `#/editor/${id}`;
        return;
      }
      if (job.status === "error") {
        busy = false;
        setBusy(false);
        setStatus(stateNode, STATUS.error.tone, STATUS.error.label);
        setTicks(bar, 0);
        detail.textContent = job.error || "El proceso falló sin detalle.";
        return;
      }
      const meta = STATUS[job.status] ?? STATUS.queued;
      setStatus(stateNode, meta.tone, meta.label);
      setTicks(bar, job.status === "queued" ? 0 : job.percent);
      detail.textContent =
        job.status === "transcribing"
          ? `${STAGES[job.stage] ?? "Transcribiendo"} · ${Math.round(job.percent)} %`
          : "En cola, esperando al worker";
    } catch (error) {
      detail.textContent = `${messageOf(error)} Reintentando…`;
    }
    timer = setTimeout(() => follow(id), 1000);
  }

  return () => {
    alive = false;
    clearTimeout(timer);
    presetPicker.dispose();
  };
}
