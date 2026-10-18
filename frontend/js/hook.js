// Gancho de apertura (estilo D de @hua_jin123): píldora con el titular y rótulos de noticiero en los primeros segundos.
// El gancho vive en el job: GET /api/jobs/{id} lo trae en el campo hook, y cada cambio se guarda con
// PUT /api/jobs/{id}/hook 400 ms después del último (null al apagar). El render usa el gancho guardado.
// localStorage solo sirve para subir una vez el gancho que quedó en este navegador antes de esta versión.
import { api } from "./api.js";
import { el, ico, messageOf, setStatus } from "./dom.js";

const DEFAULTS = { enabled: false, headline: "", kicker: "", news_title: "", news_subtitle: "", duration_s: 3 };
const DURATION = { min: 0.5, max: 10 };
const SAVE_MS = 400;
const TEXTS = [
  { key: "headline", label: "Titular", max: 80, hint: "Admite emojis. Ocupa dos líneas como máximo." },
  { key: "kicker", label: "Kicker", max: 40, hint: "Texto pequeño encima de la píldora. Opcional." },
  { key: "news_title", label: "Título del noticiero (rojo)", max: 30, hint: "Barra roja, en mayúsculas. Opcional." },
  { key: "news_subtitle", label: "Subtítulo del noticiero (azul)", max: 50, hint: "Barra azul. Opcional." },
];

// Estado de la card a partir del campo hook del job. null (o nada) = sin gancho.
export function stateOf(spec) {
  if (!spec || typeof spec !== "object") return { ...DEFAULTS };
  return sanitize({
    ...DEFAULTS,
    enabled: true,
    headline: spec.headline ?? "",
    kicker: spec.kicker ?? "",
    news_title: spec.news_title ?? "",
    news_subtitle: spec.news_subtitle ?? "",
    duration_s: spec.duration_s ?? DEFAULTS.duration_s,
  });
}

// Saneado: textos como texto, enabled como booleano y duración dentro del rango.
function sanitize(state) {
  for (const { key } of TEXTS) if (typeof state[key] !== "string") state[key] = "";
  state.enabled = state.enabled === true;
  const duration = Number(state.duration_s);
  if (!(duration >= DURATION.min && duration <= DURATION.max)) state.duration_s = DEFAULTS.duration_s;
  return state;
}

// Especificación que guarda el job: null si el gancho está apagado o sin titular.
export function hookSpec(state) {
  const headline = state.headline.trim();
  if (!state.enabled || !headline) return null;
  const optional = (text) => text.trim() || null;
  return {
    headline,
    kicker: optional(state.kicker),
    news_title: optional(state.news_title),
    news_subtitle: optional(state.news_subtitle),
    duration_s: state.duration_s,
  };
}

const sameSpec = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const legacyKey = (id) => `subs.hook.${id}`;

// Borrador de versiones anteriores, en este navegador. Solo se lee para subirlo una vez.
function legacyDraft(id) {
  try {
    const saved = JSON.parse(localStorage.getItem(legacyKey(id)));
    return saved && typeof saved === "object" ? saved : null;
  } catch {
    return null;
  }
}

function forgetLegacy(id) {
  try {
    localStorage.removeItem(legacyKey(id));
  } catch {
    // Sin almacenamiento no hay nada que borrar.
  }
}

// Card del gancho en el editor. remote es el campo hook del job; onChange(spec) avisa del preview en cada cambio.
export class HookCard {
  constructor(id, { remote, onChange }) {
    this.id = id;
    this.onChange = onChange;
    this.state = stateOf(remote);
    this.saved = remote ?? null; // lo último que confirmó el job
    this.inputs = new Map();
    this.timer = 0;
    this.queue = Promise.resolve();

    this.toggle = el("button", {
      type: "button",
      class: "cf-toggle",
      role: "switch",
      "aria-checked": "false",
      "aria-labelledby": "hook-enabled-label",
      onclick: () => this.update({ enabled: !this.state.enabled }),
    });
    this.status = el("p", { class: "cf-status", "aria-live": "polite" });
    this.showSaved();
    this.warning = el("p", { class: "cf-field__hint", text: "Escribe un titular para que el gancho se vea.", hidden: true });
    this.duration = el("input", {
      type: "number",
      class: "cf-control cf-number cf-control--sm",
      min: DURATION.min,
      max: DURATION.max,
      step: 0.5,
      inputmode: "decimal",
      "aria-labelledby": "hook-duration-label",
    });
    this.durationNote = el("p", { class: "cf-field__note t-micro", hidden: true });
    this.duration.addEventListener("input", () => {
      const value = Number(this.duration.value);
      const valid = this.duration.value !== "" && value >= DURATION.min && value <= DURATION.max;
      this.duration.setAttribute("aria-invalid", String(!valid));
      this.durationNote.hidden = valid;
      if (!valid) setStatus(this.durationNote, "danger", `Fuera de rango: permitido de ${DURATION.min} a ${DURATION.max} s.`);
      if (valid) this.update({ duration_s: value });
    });
    this.fields = el(
      "div",
      { class: "field-list" },
      ...TEXTS.map((def) => this.textRow(def)),
      el(
        "div",
        { class: "cf-field" },
        el("div", { class: "cf-field__head" }, el("span", { class: "cf-field__label", id: "hook-duration-label", text: "Duración (s)" })),
        el("div", { class: "cf-field__row" }, this.duration),
        this.durationNote,
        el("p", { class: "cf-field__hint", text: "Desde el inicio del video, de 0.5 a 10 s. Por defecto, 3." }),
      ),
      el("p", { class: "t-micro t-muted", text: "Se guarda en el video. El render lo usa en los primeros segundos." }),
    );
    this.node = el(
      "section",
      { class: "cf-kpi kpi-card", "aria-labelledby": "card-hook-title" },
      el(
        "header",
        { class: "cf-kpi__head" },
        el("span", { class: "cf-tile cf-tile--7" }, ico("play")),
        el("h2", { class: "cf-kpi__title", id: "card-hook-title", text: "Gancho de apertura" }),
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
            { class: "cf-field" },
            el(
              "div",
              { class: "cf-field__head" },
              el("span", { class: "cf-field__label", id: "hook-enabled-label", text: "Activar gancho" }),
              this.toggle,
            ),
            el("p", { class: "cf-field__hint", text: "Un titular sobre el video durante los primeros segundos." }),
            this.status,
          ),
          this.fields,
        ),
      ),
    );
    this.paint();
    // Un gancho del navegador solo se sube si el job no tiene ninguno; si el job ya tiene uno, el del navegador sobra.
    if (remote == null) this.migrate();
    else forgetLegacy(id);
  }

  textRow(def) {
    const labelId = `hook-${def.key}-label`;
    const input = el("input", {
      type: "text",
      class: "cf-control",
      maxlength: def.max,
      spellcheck: "false",
      autocomplete: "off",
      "aria-labelledby": labelId,
    });
    input.addEventListener("input", () => this.update({ [def.key]: input.value }));
    this.inputs.set(def.key, input);
    return el(
      "div",
      { class: "cf-field" },
      el("div", { class: "cf-field__head" }, el("span", { class: "cf-field__label", id: labelId, text: def.label })),
      input,
      el("p", { class: "cf-field__hint", text: def.hint }),
      def.key === "headline" ? this.warning : null,
    );
  }

  // Gancho actual: lo que se envía con el render y se dibuja en la vista previa.
  spec() {
    return hookSpec(this.state);
  }

  // Cambio del usuario: el preview va al instante. El guardado va 400 ms después del último cambio; apagar guarda enseguida.
  update(patch) {
    this.state = { ...this.state, ...patch };
    this.paint();
    this.onChange(hookSpec(this.state));
    if (patch.enabled === false) this.push();
    else this.schedule();
  }

  schedule() {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.push(), SAVE_MS);
  }

  // Las peticiones van en cadena: nunca dos a la vez, y cada una envía el estado que hay al mandarla.
  push() {
    clearTimeout(this.timer);
    this.timer = 0;
    this.queue = this.queue.then(() => this.send());
    return this.queue;
  }

  async send() {
    if (this.state.enabled && !this.state.headline.trim()) {
      setStatus(this.status, "warning", "Falta el titular: el gancho se guarda cuando lo escribas.");
      return;
    }
    const spec = hookSpec(this.state);
    if (sameSpec(spec, this.saved)) {
      this.showSaved();
      return;
    }
    setStatus(this.status, "info", "Guardando…");
    try {
      await api.saveHook(this.id, spec);
      this.saved = spec;
      this.showSaved();
    } catch (error) {
      setStatus(this.status, "danger", `No se guardó el gancho: ${messageOf(error)}`);
    }
  }

  showSaved() {
    if (this.saved) setStatus(this.status, "success", "Guardado en el video");
    else setStatus(this.status, null, "Sin gancho guardado");
  }

  // Guarda ya lo pendiente: antes de renderizar o al salir de la pantalla. Devuelve cuando el job lo confirma.
  flush() {
    return this.timer ? this.push() : this.queue;
  }

  // Migración única: el gancho del navegador se sube si el job no tiene ninguno. El navegador lo borra cuando el job
  // lo confirma; si falla, queda para el siguiente intento.
  migrate() {
    const draft = legacyDraft(this.id);
    if (!draft) return;
    const state = sanitize({ ...DEFAULTS, ...draft });
    const spec = hookSpec(state);
    if (!spec) {
      forgetLegacy(this.id);
      return;
    }
    this.state = state;
    this.paint();
    this.onChange(spec);
    this.push().then(() => {
      if (sameSpec(this.saved, spec)) forgetLegacy(this.id);
    });
  }

  // Refleja el estado en los controles. Un campo con foco no se reescribe, para no pelear con lo que se escribe.
  paint() {
    const { enabled, headline, duration_s: seconds } = this.state;
    const missing = enabled && !headline.trim();
    this.toggle.setAttribute("aria-checked", String(enabled));
    this.fields.hidden = !enabled;
    this.warning.hidden = !missing;
    this.inputs.get("headline").setAttribute("aria-invalid", String(missing));
    for (const [key, input] of this.inputs) {
      if (document.activeElement !== input) input.value = this.state[key];
    }
    if (document.activeElement !== this.duration) this.duration.value = String(seconds);
  }
}
