// Proyectos recientes y preferencias del navegador. El backend no lista jobs: los IDs se guardan aquí y su
// estado se lee de GET /api/jobs/{id}.

const RECENT_KEY = "subs.recent";
const PRESET_KEY = "subs.defaultPreset";
const MAX_RECENT = 12;
const DEFAULT_PRESET = "ken_remedie"; // default del backend (SUBS_DEFAULT_PRESET)

// Estado del job: texto y tono del punto (regla del DS: punto de 8 más texto).
export const STATUS = {
  queued: { label: "Procesando", tone: "info" },
  transcribing: { label: "Transcribiendo", tone: "info" },
  ready: { label: "Listo", tone: "success" },
  rendering: { label: "Renderizando", tone: "info" },
  done: { label: "Terminado", tone: "success" },
  error: { label: "Error", tone: "danger" },
};

// Un job en estos estados cambia solo: hay que seguirlo.
export const isBusy = (status) => status === "queued" || status === "transcribing" || status === "rendering";

export function readRecent() {
  try {
    const list = JSON.parse(localStorage.getItem(RECENT_KEY));
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

function writeRecent(list) {
  localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, MAX_RECENT)));
}

// Pone el job al frente de la lista. name es el nombre del archivo; sin él se conserva el que ya hubiera.
export function rememberJob(id, name) {
  const previous = readRecent().find((item) => item.id === id);
  const rest = readRecent().filter((item) => item.id !== id);
  writeRecent([{ id, name: name || previous?.name || `Proyecto ${id.slice(0, 6)}`, at: Date.now() }, ...rest]);
}

export function forgetJob(id) {
  writeRecent(readRecent().filter((item) => item.id !== id));
}

export function nameOf(id) {
  return readRecent().find((item) => item.id === id)?.name ?? null;
}

// Preset predeterminado para los videos nuevos: el guardado si sigue existiendo, o el default del backend.
export function defaultPresetId(presets) {
  const saved = localStorage.getItem(PRESET_KEY);
  if (saved && presets.some((preset) => preset.id === saved)) return saved;
  return presets.some((preset) => preset.id === DEFAULT_PRESET) ? DEFAULT_PRESET : presets[0]?.id;
}

export function setDefaultPreset(id) {
  localStorage.setItem(PRESET_KEY, id);
}
