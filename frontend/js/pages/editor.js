// Editor: vista previa con el overlay, cards de estilo, palabras y exportación. Cada control pide un cambio
// (onChange): el overlay lo pinta al instante y, si el campo cambia lo que calcula el motor, pide la vista previa
// de /segments. El estilo se guarda con PUT /style tras una pausa corta. Pasar el cursor o enfocar un preset lo
// muestra en vivo sobre el video (sin guardar); clic o Enter lo aplica.
import { api, fileUrl } from "../api.js";
import { debounce, el, ico, messageOf, setStatus, setTicks, status, ticksBar } from "../dom.js";
import { families } from "../fonts.js";
import { CardView } from "../controls.js";
import { SubtitleOverlay } from "../overlay.js";
import { HookCard } from "../hook.js";
import { presetGrid, sampleNode, thumbnail, unavailableNote } from "../presets.js";
import { CARDS, needsLayout, resolveStyle, sameValue, withOverride } from "../style.js";
import { STATUS, nameOf, rememberJob } from "../recents.js";
import { refreshRecent } from "../shell.js";
import { mountWords } from "./words.js";
import { mountExport } from "./exporter.js";

const PREVIEW_MS = 150;
const SAVE_MS = 400;

function pageState(text) {
  return el("div", { class: "page-state" }, el("p", { class: "t-body t-muted", role: "status", text }));
}

function missingState(error) {
  const notFound = error.status === 404;
  return el(
    "section",
    { class: "cf-card pad-20" },
    el(
      "div",
      { class: "page-state" },
      el("h1", { class: "t-page", tabindex: "-1", text: notFound ? "No encontramos este proyecto" : "No se pudo abrir el proyecto" }),
      el("p", { class: "t-body t-muted", text: messageOf(error) }),
      el("a", { class: "cf-btn cf-btn--ink cf-btn--32", href: "#/nuevo", text: "Nuevo video" }),
    ),
  );
}

// Editor de un job. Devuelve la función que lo desmonta: cancela timers y guarda el estilo pendiente.
export function mountEditor(view, ctx, { id }) {
  let alive = true;
  let timer = 0;
  const disposers = [];
  let flushPending = () => {};
  const stop = () => {
    alive = false;
    clearTimeout(timer);
    flushPending();
    for (const dispose of disposers.splice(0)) dispose();
  };

  view.replaceChildren(pageState("Abriendo el proyecto…"));
  load();
  return stop;

  async function load() {
    let job;
    try {
      job = await api.job(id);
    } catch (error) {
      if (alive) view.replaceChildren(missingState(error));
      return;
    }
    if (!alive) return;
    rememberJob(id, nameOf(id));
    refreshRecent();
    try {
      if (job.status === "queued" || job.status === "transcribing") waitFor(job);
      else if (job.status === "error") failed(job);
      else build(job);
    } catch (error) {
      // Un fallo al armar la pantalla se muestra tal cual, en vez de dejar el texto de carga.
      console.error(error);
      if (alive) view.replaceChildren(pageState(`No se pudo abrir el editor: ${error.message}`));
    }
  }

  // Job en transcripción: se muestra el progreso y, cuando queda listo, se abre el editor.
  function waitFor(job) {
    const meta = STATUS[job.status];
    const label = status(meta.tone, meta.label);
    const bar = ticksBar(100, 1);
    const detail = el("p", { class: "t-micro t-muted" });
    view.replaceChildren(
      el("header", { class: "page-head" }, el("h1", { class: "t-page", tabindex: "-1", text: nameOf(id) ?? "Proyecto en proceso" })),
      el("section", { class: "cf-card pad-20" }, el("div", { class: "progress__head" }, label), bar, detail),
    );
    const tick = async () => {
      try {
        const next = await api.job(id);
        if (!alive) return;
        if (next.status === "queued" || next.status === "transcribing") {
          const current = STATUS[next.status];
          setStatus(label, current.tone, current.label);
          setTicks(bar, next.status === "queued" ? 0 : next.percent);
          detail.textContent = next.status === "transcribing" ? `${Math.round(next.percent)} %` : "En cola, esperando al worker";
          timer = setTimeout(tick, 1000);
          return;
        }
        load();
      } catch (error) {
        if (!alive) return;
        detail.textContent = `${messageOf(error)} Reintentando…`;
        timer = setTimeout(tick, 2000);
      }
    };
    timer = setTimeout(tick, 1000);
  }

  function failed(job) {
    view.replaceChildren(
      el("header", { class: "page-head" }, el("h1", { class: "t-page", tabindex: "-1", text: nameOf(id) ?? "Proyecto con error" })),
      el(
        "section",
        { class: "cf-card pad-20" },
        el(
          "div",
          { class: "page-state" },
          status(STATUS.error.tone, STATUS.error.label),
          el("p", { class: "t-body t-soft", text: job.error || "El proceso falló sin detalle." }),
          el("a", { class: "cf-btn cf-btn--white cf-btn--32", href: "#/nuevo", text: "Subir otro video" }),
        ),
      ),
    );
  }

  function build(job) {
    const presets = ctx.presets;
    const chosen = presets.find((preset) => preset.id === job.preset) ?? presets[0];
    const state = {
      preset: chosen.id,
      presetStyle: chosen.style,
      overrides: chosen.id === job.preset ? job.overrides ?? {} : {},
    };
    state.style = resolveStyle(state.presetStyle, state.overrides);
    const name = nameOf(id) ?? `Proyecto ${id.slice(0, 6)}`;
    let dirty = false;
    let previewSeq = 0;
    let saving = Promise.resolve();
    let appliedSegments = [];
    let candidate = null; // último preset que pasó el cursor o el foco: lo que compara "Comparar"
    let previewing = null; // preset que se muestra en vivo ahora mismo, o null
    let previewSeqLive = 0;
    let playback = null; // tiempo y silencio del video antes de la vista en vivo, para restaurarlos

    // Vista previa: el video original con el overlay encima. El marco conserva la proporción del video.
    const video = el("video", {
      controls: true,
      playsinline: true,
      preload: "metadata",
      src: fileUrl(id, "input"),
      "aria-label": "Video original",
    });
    const frame = el("div", { class: "frame", style: { aspectRatio: `${job.video.width} / ${job.video.height}` } }, video);
    const overlay = new SubtitleOverlay(frame, job.video);
    disposers.push(() => overlay.resizer?.disconnect?.());
    const preview = el(
      "section",
      { class: "cf-card cf-card--chart editor__preview", "aria-label": "Vista previa" },
      frame,
      el(
        "div",
        { class: "editor__caption" },
        el("span", { class: "t-card", text: name }),
        el("span", { class: "t-micro t-muted", text: `${job.video.width} × ${job.video.height} · ${job.video.duration.toFixed(1)} s` }),
      ),
    );

    const saveState = el("span", { class: "cf-status", "aria-live": "polite" });
    setStatus(saveState, null, "Sin cambios");
    const header = el(
      "header",
      { class: "page-head" },
      el(
        "div",
        { class: "page-head__row" },
        el("div", { class: "page-head__title" }, el("h1", { class: "t-page", tabindex: "-1", text: name })),
        saveState,
      ),
    );

    // Card de preset: miniaturas reales del job (o muestras CSS si el backend no las da). Vista en vivo al pasar el
    // cursor o enfocar; Comparar abre dos cuadros a 540 px, el actual y el último que pasó el cursor.
    const compareButton = el(
      "button",
      { type: "button", class: "cf-btn cf-btn--white cf-btn--32", disabled: true, onclick: () => openCompare() },
      "Comparar",
    );
    const modeNote = el("p", { class: "t-micro t-muted", text: "Cargando miniaturas…" });
    const grid = presetGrid({
      presets,
      selectedId: state.preset,
      job: { id },
      columns: 2,
      chip: "Seleccionado",
      onPick: (presetId) => choosePreset(presetId),
      onEnter: (presetId, time) => startPreview(presetId, time),
      onLeave: () => endPreview(),
      onMode: (mode, error) => {
        modeNote.textContent = mode === "frames" ? "Miniaturas reales del video." : unavailableNote(error) ?? "Muestras aproximadas: el backend todavía no entrega miniaturas para este video.";
      },
    });
    disposers.push(grid.dispose);
    const presetCard = el(
      "section",
      { class: "cf-kpi kpi-card", "aria-labelledby": "card-preset-title" },
      el(
        "header",
        { class: "cf-kpi__head" },
        el("span", { class: "cf-tile cf-tile--4" }, ico("sparkle")),
        el("h2", { class: "cf-kpi__title", id: "card-preset-title", text: "Preset" }),
      ),
      el("div", { class: "cf-kpi__rule" }),
      el(
        "div",
        { class: "cf-kpi__body cf-kpi__body--auto" },
        el(
          "div",
          { class: "field-list" },
          el(
            "div",
            { class: "preset-toolbar" },
            el("p", { class: "cf-field__hint", text: "Pasa el cursor para verlo en el video. Elegir uno descarta los ajustes manuales." }),
            compareButton,
          ),
          modeNote,
          grid.node,
        ),
      ),
    );

    // Diálogo de comparación: el preset actual y el candidato, a 540 px de ancho cada uno.
    const compareLeft = el("span", { class: "compare__frame" });
    const compareRight = el("span", { class: "compare__frame" });
    const compareLeftLabel = el("figcaption", { class: "t-micro t-muted" });
    const compareRightLabel = el("figcaption", { class: "t-micro t-muted" });
    const useCandidate = el("button", { type: "button", class: "cf-btn cf-btn--ink cf-btn--32", onclick: () => useFromCompare() });
    const compare = el(
      "dialog",
      { class: "compare", "aria-labelledby": "compare-title" },
      el(
        "div",
        { class: "compare__head" },
        el("h2", { class: "t-card", id: "compare-title", text: "Comparar presets" }),
        el("button", { type: "button", class: "cf-btn cf-btn--white cf-btn--32", "data-close": "", onclick: () => compare.close(), text: "Cerrar" }),
      ),
      el(
        "div",
        { class: "compare__grid" },
        el("figure", { class: "compare__item" }, compareLeft, compareLeftLabel),
        el("figure", { class: "compare__item" }, compareRight, compareRightLabel),
      ),
      el("div", { class: "compare__foot" }, useCandidate),
    );
    let compareCandidate = null;
    let compareLeftPreset = null;

    const cards = CARDS.map((card) => new CardView(card, { families: families(), onChange: (key, value, extra) => changeField(key, value, extra) }));
    // El gancho va antes de Avanzado, que sigue siendo la última card.
    const hookCard = new HookCard(id, { remote: job.hook, onChange: (spec) => overlay.setHook(spec) });
    disposers.push(() => hookCard.flush());
    const cardsHost = el("div", { class: "editor__cards" }, presetCard, ...cards.slice(0, -1).map((card) => card.node), hookCard.node, cards[cards.length - 1].node);
    const wordsHost = el("section", { class: "cf-panel editor__section" });
    const exportHost = el("section", { class: "cf-card pad-20 editor__section" });
    view.replaceChildren(header, el("div", { class: "editor" }, preview, cardsHost), wordsHost, exportHost, compare);

    // Error del servidor al guardar o previsualizar. Un 422 de un campo («font_size inválido: …») va junto a su control.
    function reportError(error) {
      const key = /^([a-z_]+) inválido/.exec(error?.detail ?? "")?.[1] ?? null;
      const placed = error?.status === 422 && key !== null && cards.some((card) => card.showError(key, error.detail));
      setStatus(saveState, "danger", placed ? "Revisa el campo marcado." : messageOf(error));
    }

    function paint() {
      for (const card of cards) card.sync(state.style);
      overlay.setStyle(state.style);
    }

    // Un cambio puede traer otros campos (text_case apaga uppercase). Solo entran los que cambian de verdad.
    function changeField(key, value, extra = {}) {
      const patch = { [key]: value, ...extra };
      const changed = Object.keys(patch).filter((name) => !sameValue(state.style[name], patch[name]));
      if (!changed.length) return;
      for (const name of changed) state.overrides = withOverride(state.overrides, state.presetStyle, name, patch[name]);
      state.style = resolveStyle(state.presetStyle, state.overrides);
      paint();
      markDirty();
      if (changed.some(needsLayout)) previewSoon();
    }

    function choosePreset(presetId) {
      endPreview();
      if (presetId === state.preset) return;
      const next = presets.find((preset) => preset.id === presetId);
      state.preset = next.id;
      state.presetStyle = next.style;
      state.overrides = {};
      state.style = resolveStyle(next.style, {});
      grid.setSelected(state.preset);
      paint();
      markDirty();
      previewSoon();
    }

    // Vista en vivo: /segments del preset candidato (sin overrides) sobre el video. Si el video está en pausa,
    // reproduce desde el cuadro de la miniatura, silenciado, para que se vea el movimiento.
    function startPreview(presetId, time) {
      if (presetId === state.preset) {
        endPreview();
        return;
      }
      candidate = presetId;
      compareButton.disabled = false;
      const preset = presets.find((item) => item.id === presetId);
      const token = ++previewSeqLive;
      previewing = presetId;
      if (video.paused && time != null) {
        playback ??= { time: video.currentTime, muted: video.muted };
        video.muted = true;
        video.currentTime = Number(time);
        video.play().catch(() => {});
      }
      api
        .segments(id, { preset: presetId, overrides: {} })
        .then((segments) => {
          if (!alive || token !== previewSeqLive) return;
          overlay.setStyle(preset.style);
          overlay.setSegments(segments);
        })
        .catch((error) => {
          if (alive && token === previewSeqLive) setStatus(saveState, "danger", messageOf(error));
        });
    }

    // Fin de la vista en vivo: vuelve a lo guardado en pantalla y restaura el video si lo movimos.
    function endPreview() {
      previewSeqLive += 1;
      if (!previewing) return;
      previewing = null;
      overlay.setStyle(state.style);
      overlay.setSegments(appliedSegments);
      if (playback) {
        video.pause();
        video.currentTime = playback.time;
        video.muted = playback.muted;
        playback = null;
      }
    }

    async function openCompare() {
      if (!candidate) return;
      compareLeftPreset = state.preset;
      compareCandidate = candidate;
      const left = presets.find((item) => item.id === compareLeftPreset);
      const right = presets.find((item) => item.id === compareCandidate);
      compareLeftLabel.textContent = `Actual · ${left.label}`;
      compareRightLabel.textContent = `Comparado · ${right.label}`;
      useCandidate.textContent = `Usar ${right.label}`;
      for (const [slot, preset] of [
        [compareLeft, left],
        [compareRight, right],
      ]) {
        slot.replaceChildren(el("span", { class: "compare__stage" }, sampleNode(preset)));
        thumbnail(id, preset.id, 540)
          .then((frame) => {
            if (!alive) return;
            slot.replaceChildren(el("img", { class: "compare__img", src: frame.src, alt: `Cuadro con el preset ${preset.label}` }));
          })
          .catch(() => {});
      }
      compare.showModal();
    }

    function useFromCompare() {
      if (!compareCandidate) return;
      compare.close();
      choosePreset(compareCandidate);
    }

    // Vista previa con /segments: el estilo de la pantalla, sin guardar nada. Las respuestas viejas se descartan.
    const previewSoon = debounce(() => previewNow(), PREVIEW_MS);
    async function previewNow() {
      const seq = ++previewSeq;
      try {
        const segments = await api.segments(id, { preset: state.preset, overrides: state.overrides });
        if (!alive || seq !== previewSeq) return;
        appliedSegments = segments;
        if (!previewing) overlay.setSegments(segments);
      } catch (error) {
        if (alive && seq === previewSeq) reportError(error);
      }
    }

    // Guardado con PUT /style. Las peticiones van en cadena: nunca dos a la vez, y siempre con el último estilo.
    const saveSoon = debounce(() => queueSave(), SAVE_MS);
    function markDirty() {
      dirty = true;
      setStatus(saveState, "info", "Cambios sin guardar");
      saveSoon();
    }
    function queueSave() {
      saving = saving.then(saveNow);
      return saving;
    }
    async function saveNow() {
      if (!dirty) return;
      dirty = false;
      setStatus(saveState, "info", "Guardando…");
      try {
        await api.saveStyle(id, state.preset, state.overrides);
        if (alive) setStatus(saveState, "success", "Guardado");
      } catch (error) {
        if (alive) reportError(error);
      }
    }
    // Antes de renderizar o de bajar el .ass, el estilo tiene que estar guardado.
    async function flush() {
      saveSoon.cancel();
      if (dirty) queueSave();
      await saving;
    }
    flushPending = () => {
      saveSoon.cancel();
      if (dirty) queueSave();
    };

    disposers.push(mountWords(wordsHost, { id, flush, onSaved: () => previewNow() }));
    // Antes de renderizar o de bajar el .ass, se guardan el estilo y el gancho pendientes.
    const flushAll = async () => {
      await flush();
      await hookCard.flush();
    };
    disposers.push(mountExport(exportHost, { id, flush: flushAll, hook: () => hookCard.spec() }));

    // Reproducción: el overlay sigue al video cuadro a cuadro mientras suena (karaoke y barrido lo necesitan).
    let frameId = 0;
    const loop = () => {
      overlay.show(video.currentTime);
      if (!video.paused && !video.ended) frameId = requestAnimationFrame(loop);
    };
    video.addEventListener("play", () => {
      cancelAnimationFrame(frameId);
      loop();
    });
    for (const type of ["pause", "ended", "seeked", "timeupdate"]) {
      video.addEventListener(type, () => overlay.show(video.currentTime));
    }
    disposers.push(() => cancelAnimationFrame(frameId));

    overlay.setHook(hookCard.spec());
    paint();
    previewNow();
    if (chosen.id !== job.preset) markDirty();
  }
}
