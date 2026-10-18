// Presets: catálogo con la miniatura real de cada uno (del job listo más reciente). Clic en una tarjeta lo deja
// como predeterminado para los videos nuevos; se guarda en el navegador.
import { api } from "../api.js";
import { el } from "../dom.js";
import { presetGrid, unavailableNote } from "../presets.js";
import { defaultPresetId, readRecent, setDefaultPreset } from "../recents.js";

// Primer proyecto de la lista reciente que ya está listo: de ahí salen las miniaturas. Sin ninguno, muestras CSS.
async function latestReadyJob() {
  for (const item of readRecent().slice(0, 6)) {
    try {
      const job = await api.job(item.id);
      if (job.status === "ready" || job.status === "done") return { id: item.id, name: item.name };
    } catch {
      // Un proyecto que ya no existe no bloquea el catálogo.
    }
  }
  return null;
}

export function mountPresets(view, ctx) {
  let alive = true;
  const title = el("h1", { class: "t-page", tabindex: "-1", text: "Presets" });
  const intro = el("p", {
    class: "t-body t-muted",
    text: "Clic en una tarjeta deja el preset como predeterminado para los videos nuevos. Cada video conserva sus propios ajustes.",
  });
  const note = el("p", { class: "t-micro t-muted", text: "Cargando miniaturas…" });
  const host = el("div", { class: "preset-page" });
  view.replaceChildren(el("header", { class: "page-head" }, title, intro), note, host);
  title.focus({ preventScroll: true });

  let grid = null;
  const show = (job) => {
    grid?.dispose();
    grid = presetGrid({
      presets: ctx.presets,
      selectedId: defaultPresetId(ctx.presets),
      job,
      chip: "Predeterminado para videos nuevos",
      label: "Presets",
      onMode: (mode, error) => {
        if (job) note.textContent = mode === "frames" ? `Cuadros reales del proyecto ${job.name}, con el subtítulo quemado por libass.` : unavailableNote(error) ?? "Muestras aproximadas: el backend todavía no entrega cuadros para este proyecto.";
      },
      onPick: (id) => {
        setDefaultPreset(id);
        grid.setSelected(id);
      },
    });
    host.replaceChildren(grid.node);
    note.textContent = job ? `Cargando cuadros del proyecto ${job.name}…` : "Muestras aproximadas: sube un video para ver cuadros reales.";
  };
  show(null);
  latestReadyJob().then((job) => {
    if (alive) show(job);
  });

  return () => {
    alive = false;
    grid?.dispose();
  };
}
