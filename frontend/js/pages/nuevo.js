// Nuevo video: subida con progreso de subida y de transcripción. Cuando el job queda listo, abre el editor.
// Antes de subir, el preset se elige sobre muestras CSS aproximadas: la miniatura real aparece en el editor.
import { api } from "../api.js";
import { el, fileLabel, ico, megabytes, messageOf, setStatus, setTicks, status, ticksBar } from "../dom.js";
import { track } from "../controls.js";
import { presetGrid } from "../presets.js";
import { STATUS, defaultPresetId, rememberJob } from "../recents.js";
import { refreshRecent } from "../shell.js";
import { RETRY_DELAYS, UploadCancelled, pendingUpload, sendVideo } from "../upload.js";

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
const mb = (bytes) => `${Math.round(bytes / (1024 * 1024))} MB`;
const hintFor = (bytes) => (bytes ? `mp4, mov o webm, hasta ${mb(bytes)}` : "mp4, mov o webm");
// 83 -> "quedan 1 min 23 s". Sin velocidad todavía, el tiempo restante no se conoce.
function etaText(seconds) {
  if (!Number.isFinite(seconds)) return "calculando el tiempo restante";
  const s = Math.max(1, Math.round(seconds));
  if (s < 60) return `quedan ${s} s`;
  if (s < 3600) return `quedan ${Math.floor(s / 60)} min ${s % 60} s`;
  return `quedan ${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
}

export function mountNuevo(view, ctx) {
  let alive = true;
  let timer = 0;
  let file = null;
  let language = "";
  let presetId = defaultPresetId(ctx.presets);
  let busy = false;
  let config = null;
  let abort = null;
  let resumeNote = "";

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
  // Cancelar solo durante la subida: cuando el servidor crea el trabajo ya no se puede parar.
  const cancelButton = el("button", { type: "button", class: "cf-btn cf-btn--white cf-btn--32", onclick: () => abort?.abort() }, "Cancelar");
  const cancelRow = el("div", { class: "progress__actions", hidden: true }, cancelButton);
  const progress = el(
    "section",
    { class: "cf-card pad-20", hidden: true, "aria-labelledby": "nuevo-progress-title" },
    el("div", { class: "progress__head" }, el("h2", { class: "t-card", id: "nuevo-progress-title", text: "Progreso" }), stateNode),
    bar,
    detail,
    cancelRow,
  );

  view.replaceChildren(el("header", { class: "page-head" }, title, intro), el("div", { class: "stack" }, form, progress));
  title.focus({ preventScroll: true });

  // Límites del backend (GET /api/config): max_upload_bytes para validar y chunk_bytes para subir por trozos.
  // Sin respuesta no hay cifra ni chunk_bytes: el video va por POST /api/jobs y el servidor sigue validando el tamaño.
  const ready = api
    .config()
    .then((loaded) => {
      config = loaded;
      if (!Number.isFinite(loaded?.max_upload_bytes)) return;
      maxBytes = loaded.max_upload_bytes;
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

  // Motivo para no subir el archivo, o "" si puede subirse. Sin límite cargado de /api/config no se comprueba el tamaño máximo.
  function problemOf(next) {
    if (!FORMAT.test(next.name)) return "Formato no admitido: usa mp4, mov o webm.";
    if (!next.size) return "El archivo está vacío.";
    if (maxBytes !== null && next.size > maxBytes) return `El archivo pesa ${megabytes(next.size)} y el máximo es ${mb(maxBytes)}.`;
    return "";
  }

  // Texto bajo el nombre: el tamaño y, si hay una subida a medias de este archivo, que se reanudará.
  function fileHint(next) {
    return `${megabytes(next.size)} · ${pendingUpload(next) ? "subida a medias: se reanudará" : "listo para subir"}`;
  }

  function refuse(problem) {
    file = null;
    start.disabled = true;
    dropTitle.textContent = DROP_TITLE;
    dropHint.textContent = hintFor(maxBytes);
    say("danger", problem);
  }

  function choose(next) {
    if (busy) return;
    const problem = problemOf(next);
    if (problem) {
      refuse(problem);
      return;
    }
    file = next;
    dropTitle.textContent = fileLabel(next.name);
    dropHint.textContent = fileHint(next);
    start.disabled = false;
    say(null, "");
  }

  // Mientras se sube, recargar o cerrar la pestaña avisa. Los trozos ya enviados se conservan y la subida se reanuda.
  const warnLeaving = (event) => {
    event.preventDefault();
    event.returnValue = "";
  };

  // El texto solo cambia cuando cambia el estado, para que el anuncio de lectores de pantalla no se repita.
  function setState(tone, label) {
    if (stateNode.textContent !== label) setStatus(stateNode, tone, label);
  }

  // Progreso: la barra marca los bytes enviados; el texto dice porcentaje, velocidad y tiempo restante.
  function showProgress({ sent, total, speed, eta }) {
    if (!alive) return;
    const fraction = total ? sent / total : 0;
    setState("info", "Subiendo video");
    setTicks(bar, fraction * 100);
    const mbps = speed / (1024 * 1024);
    const rate = speed ? `${mbps < 1 ? mbps.toFixed(2) : mbps.toFixed(1)} MB/s · ${etaText(eta)}` : "calculando la velocidad";
    detail.textContent = `${resumeNote}Subido ${Math.round(fraction * 100)} % · ${rate}`;
  }

  // Avisos de la subida: reanudación, reintentos y el paso final (crear el trabajo).
  function showState(event) {
    if (!alive) return;
    if (event.kind === "resume") {
      resumeNote = `Reanudada: ${event.done} de ${event.total} fragmentos ya estaban en el servidor. `;
    }
    if (event.kind === "retry") {
      setState("warning", "Reintentando");
      detail.textContent = `Falló el fragmento ${event.chunk + 1} de ${event.total}. ${event.message} Reintento ${event.attempt} de ${RETRY_DELAYS.length} en ${event.delay / 1000} s.`;
    }
    if (event.kind === "complete") {
      cancelRow.hidden = true;
      setState("info", "Creando el trabajo");
      detail.textContent = `${resumeNote}Comprobando el archivo en el servidor…`;
    }
  }

  async function upload() {
    if (!file || busy) return;
    await ready;
    // El límite puede llegar después de elegir el archivo: se vuelve a comprobar antes de subir.
    const problem = problemOf(file);
    if (problem) {
      refuse(problem);
      return;
    }
    const picked = file;
    busy = true;
    abort = new AbortController();
    window.addEventListener("beforeunload", warnLeaving);
    resumeNote = "";
    setBusy(true);
    say(null, "");
    progress.hidden = false;
    cancelRow.hidden = false;
    setState("info", "Subiendo video");
    setTicks(bar, 0);
    detail.textContent = "";
    try {
      const { job_id: id } = await sendVideo({
        file: picked,
        preset: presetId,
        language,
        config,
        signal: abort.signal,
        onProgress: showProgress,
        onState: showState,
      });
      cancelRow.hidden = true;
      window.removeEventListener("beforeunload", warnLeaving);
      rememberJob(id, picked.name);
      refreshRecent();
      follow(id);
    } catch (error) {
      busy = false;
      setBusy(false);
      progress.hidden = true;
      cancelRow.hidden = true;
      window.removeEventListener("beforeunload", warnLeaving);
      if (error instanceof UploadCancelled) {
        say("info", "Subida cancelada.");
      } else {
        say("danger", messageOf(error));
      }
      dropHint.textContent = fileHint(picked);
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
