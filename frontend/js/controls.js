// Controles de los campos de estilo, generados desde FIELDS. Cada control lee su valor del estilo (update) y avisa
// de los cambios con ctx.onChange(key, value). Las cards reconcilian sus campos: un campo que sigue visible no se
// recrea, así no se pierde el foco mientras se escribe.
import { alignmentOf, contextFor, defOf, fieldsFor, optionsOf, placementOf } from "./style.js";
import { el, fixed, ico, roundTo, setStatus } from "./dom.js";

let seq = 0;
const HEX = /^#?([0-9a-fA-F]{6})$/;
const PUNCTUATION = /^[^\p{L}\p{N}\s]{0,20}$/u;
const STEP_KEYS = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };

// Grupo de radios (track de filtros) con flechas y roving tabindex. onPick recibe el valor elegido.
export function track(options, labelledBy, onPick) {
  const chips = options.map(([value, text]) =>
    el("button", {
      type: "button",
      class: "cf-track__chip",
      role: "radio",
      "aria-checked": "false",
      tabindex: "-1",
      "data-value": value,
      text,
      onclick: () => onPick(value),
    }),
  );
  const node = el("div", { class: "cf-track cf-track--fill", role: "radiogroup", "aria-labelledby": labelledBy }, chips);
  node.addEventListener("keydown", (event) => {
    const step = STEP_KEYS[event.key];
    if (!step) return;
    event.preventDefault();
    const index = Math.max(0, chips.indexOf(document.activeElement));
    const next = chips[(index + step + chips.length) % chips.length];
    next.focus();
    onPick(next.dataset.value);
  });
  return {
    node,
    set(value) {
      for (const chip of chips) {
        const on = chip.dataset.value === String(value);
        chip.setAttribute("aria-checked", String(on));
        chip.tabIndex = on ? 0 : -1;
      }
      if (!chips.some((chip) => chip.tabIndex === 0)) chips[0].tabIndex = 0;
    },
  };
}

function toggleControl(key, ctx, labelId) {
  let on = false;
  const node = el("button", {
    type: "button",
    class: "cf-toggle",
    role: "switch",
    "aria-checked": "false",
    "aria-labelledby": labelId,
    onclick: () => ctx.onChange(key, !on),
  });
  return {
    head: node,
    update(style) {
      on = !!style[key];
      node.setAttribute("aria-checked", String(on));
    },
  };
}

// Número con deslizador y campo numérico. percent: el valor guardado es una fracción y se muestra en %. Un valor fuera de
// rango no se recorta ni se envía: el campo se marca y note explica el rango permitido bajo el control.
function numberControl(key, def, ctx, labelId, percent, note) {
  const k = percent ? 100 : 1;
  const low = def.min * k;
  const high = def.max * k;
  const shownDigits = percent ? Math.max(0, def.digits - 2) : def.digits;
  const range = el("input", { type: "range", class: "cf-range", min: low, max: high, step: def.step * k, "aria-labelledby": labelId });
  const number = el("input", {
    type: "number",
    class: "cf-control cf-number cf-control--sm",
    min: low,
    max: high,
    step: def.step * k,
    inputmode: "decimal",
    "aria-labelledby": labelId,
    "aria-describedby": note.id,
  });
  const unit = percent ? " %" : "";
  let shown = 0;
  let invalid = false;
  // Marca o desmarca un valor fuera de rango. Mientras está marcado, el campo conserva lo que escribió el usuario.
  const flag = (on) => {
    invalid = on;
    number.setAttribute("aria-invalid", String(on));
    note.hidden = !on;
    if (on) setStatus(note, "danger", `Fuera de rango: permitido de ${fixed(low, shownDigits)}${unit} a ${fixed(high, shownDigits)}${unit}.`);
  };
  // Un valor fuera de rango no se recorta ni se envía: se marca y se explica bajo el control.
  const commit = (raw) => {
    const value = Number(raw);
    if (raw === "" || !Number.isFinite(value)) return;
    if (value < low || value > high) {
      flag(true);
      return;
    }
    flag(false);
    ctx.onChange(key, roundTo(value / k, def.digits));
  };
  range.addEventListener("input", () => commit(range.value));
  number.addEventListener("input", () => commit(number.value));
  number.addEventListener("blur", () => {
    if (!invalid) number.value = fixed(shown, shownDigits);
  });
  return {
    body: el("div", { class: "cf-field__row" }, range, number),
    update(style) {
      shown = style[key] * k;
      range.value = String(shown);
      if (!invalid && document.activeElement !== number) number.value = fixed(shown, shownDigits);
    },
  };
}

// Color: swatch nativo más código hex dentro de un solo control.
function colorControl(key, label, ctx, labelId) {
  const swatch = el("input", { type: "color", class: "cf-swatch-input", "aria-label": `${label}: selector de color` });
  const hex = el("input", { type: "text", class: "cf-hex", maxlength: 7, spellcheck: "false", autocomplete: "off", "aria-labelledby": labelId });
  const body = el("div", { class: "cf-control cf-color" }, swatch, hex);
  let current = "#FFFFFF";
  swatch.addEventListener("input", () => ctx.onChange(key, swatch.value.toUpperCase()));
  hex.addEventListener("input", () => {
    const match = HEX.exec(hex.value.trim());
    hex.setAttribute("aria-invalid", String(!match));
    if (match) ctx.onChange(key, `#${match[1].toUpperCase()}`);
  });
  hex.addEventListener("blur", () => {
    hex.value = current;
    hex.setAttribute("aria-invalid", "false");
  });
  return {
    body,
    update(style) {
      current = style[key].toUpperCase();
      swatch.value = current.toLowerCase();
      if (document.activeElement !== hex) hex.value = current;
    },
  };
}

// Campo que puede estar apagado (valor null): un toggle en la cabecera y, si está encendido, su control.
function nullableControl(key, def, ctx, labelId, note) {
  const inner =
    def.base === "color"
      ? colorControl(key, def.label, ctx, labelId)
      : numberControl(key, def, ctx, labelId, def.base === "percent", note);
  const off = el("p", { class: "cf-field__off", text: def.off });
  let on = false;
  let last = null;
  const toggle = el("button", {
    type: "button",
    class: "cf-toggle",
    role: "switch",
    "aria-checked": "false",
    "aria-labelledby": labelId,
    onclick: () => ctx.onChange(key, on ? null : def.def(last)),
  });
  return {
    head: toggle,
    body: el("div", { class: "cf-field__stack" }, inner.body, off),
    update(style) {
      last = style;
      on = style[key] != null;
      toggle.setAttribute("aria-checked", String(on));
      inner.body.hidden = !on;
      off.hidden = on;
      if (on) inner.update(style);
    },
  };
}

// Track de opciones. read (opcional) da el valor mostrado; patch, los campos que van con el valor elegido.
function trackField(key, def, ctx, labelId) {
  const control = track(optionsOf(def), labelId, (value) => ctx.onChange(key, value, def.patch?.(value)));
  return { body: control.node, update: (style) => control.set(def.read ? def.read(style) : style[key]) };
}

// Familia de letra. nullable: la opción "" guarda null (el campo usa la familia del texto).
function selectField(key, def, ctx, labelId) {
  const select = el("select", {
    class: "cf-control cf-select",
    "aria-labelledby": labelId,
    onchange: () => ctx.onChange(key, def.nullable && select.value === "" ? null : select.value),
  });
  if (def.nullable) select.append(el("option", { value: "", text: def.nullable }));
  select.append(...ctx.families.map((name) => el("option", { value: name, text: name })));
  return {
    body: select,
    update(style) {
      select.value = style[key] ?? "";
    },
  };
}

// Alineación numpad (1-9) como dos tracks: vertical y horizontal. y_pct la anula, por eso su campo se oculta.
function alignField(key, ctx, labelId) {
  let row = "bottom";
  let col = "center";
  const emit = () => ctx.onChange(key, alignmentOf(row, col));
  const vertical = track(
    [
      ["top", "Arriba"],
      ["mid", "Medio"],
      ["bottom", "Abajo"],
    ],
    `${labelId}-v`,
    (value) => {
      row = value;
      emit();
    },
  );
  const horizontal = track(
    [
      ["left", "Izquierda"],
      ["center", "Centro"],
      ["right", "Derecha"],
    ],
    `${labelId}-h`,
    (value) => {
      col = value;
      emit();
    },
  );
  return {
    body: el(
      "div",
      { class: "cf-field__stack" },
      el("span", { class: "cf-field__hint", id: `${labelId}-v`, text: "Vertical" }),
      vertical.node,
      el("span", { class: "cf-field__hint", id: `${labelId}-h`, text: "Horizontal" }),
      horizontal.node,
    ),
    update(style) {
      const place = placementOf(style[key]);
      row = place.row;
      col = place.col;
      vertical.set(row);
      horizontal.set(col);
    },
  };
}

function textField(key, ctx, labelId) {
  const input = el("input", {
    type: "text",
    class: "cf-control",
    maxlength: 20,
    spellcheck: "false",
    autocomplete: "off",
    "aria-labelledby": labelId,
  });
  input.addEventListener("input", () => {
    const valid = PUNCTUATION.test(input.value);
    input.setAttribute("aria-invalid", String(!valid));
    if (valid) ctx.onChange(key, input.value);
  });
  return {
    body: input,
    update(style) {
      if (document.activeElement === input) return;
      input.value = style[key];
      input.setAttribute("aria-invalid", "false");
    },
  };
}

// Lista de palabras separadas por comas o espacios (split_before_words). Se guarda al escribir.
function wordsField(key, ctx, labelId) {
  const input = el("input", {
    type: "text",
    class: "cf-control",
    spellcheck: "false",
    autocomplete: "off",
    "aria-labelledby": labelId,
  });
  input.addEventListener("input", () => ctx.onChange(key, input.value.split(/[\s,]+/).filter(Boolean)));
  return {
    body: input,
    update(style) {
      if (document.activeElement === input) return;
      input.value = (style[key] ?? []).join(", ");
    },
  };
}

// Texto a valor de un campo raw: vacío o "null" es null; true y false, números y listas u objetos JSON se convierten.
// Lo demás queda como texto.
function parseRaw(text) {
  const trimmed = text.trim();
  if (trimmed === "" || trimmed === "null") return null;
  if (trimmed === "true" || trimmed === "false") return trimmed === "true";
  if (Number.isFinite(Number(trimmed))) return Number(trimmed);
  if (/^[[{]/.test(trimmed)) {
    try {
      return JSON.parse(trimmed);
    } catch {
      return text;
    }
  }
  return text;
}

// Campo que el editor no conoce (defOf): su valor se edita como texto y vuelve con el tipo que trae.
function rawField(key, ctx, labelId) {
  const input = el("input", { type: "text", class: "cf-control", spellcheck: "false", autocomplete: "off", "aria-labelledby": labelId });
  input.addEventListener("change", () => ctx.onChange(key, parseRaw(input.value)));
  return {
    body: input,
    update(style) {
      if (document.activeElement === input) return;
      const value = style[key];
      input.value = value == null ? "" : typeof value === "string" ? value : JSON.stringify(value);
    },
  };
}

function buildControl(key, def, ctx, labelId, note) {
  switch (def.kind) {
    case "toggle":
      return toggleControl(key, ctx, labelId);
    case "number":
      return numberControl(key, def, ctx, labelId, false, note);
    case "nullable":
      return nullableControl(key, def, ctx, labelId, note);
    case "track":
      return trackField(key, def, ctx, labelId);
    case "select":
      return selectField(key, def, ctx, labelId);
    case "color":
      return colorControl(key, def.label, ctx, labelId);
    case "align":
      return alignField(key, ctx, labelId);
    case "text":
      return textField(key, ctx, labelId);
    case "words":
      return wordsField(key, ctx, labelId);
    case "raw":
      return rawField(key, ctx, labelId);
    default:
      throw new Error(`Tipo de campo desconocido: ${def.kind}`);
  }
}

// Fila de un campo: label y control. Los toggles van en la cabecera, junto al label. def viene de defOf(key, style).
export function createField(key, ctx, def) {
  const labelId = `fl-${key}-${++seq}`;
  // Aviso bajo el control: el rango permitido, o el detail de un 422 del servidor (showError).
  const note = el("p", { class: "cf-field__note t-micro", id: `${labelId}-nota`, hidden: true });
  const control = buildControl(key, def, ctx, labelId, note);
  const node = el(
    "div",
    { class: "cf-field", "data-field": key },
    el("div", { class: "cf-field__head" }, el("span", { class: "cf-field__label", id: labelId, text: def.label }), control.head ?? null),
    control.body ?? null,
    note,
  );
  return {
    node,
    update: (style) => control.update(style),
    showError(text) {
      setStatus(note, "danger", text);
      note.hidden = false;
    },
  };
}

// Deja en container exactamente estos nodos, en este orden, sin mover los que ya están bien colocados.
function reconcile(container, nodes) {
  const keep = new Set(nodes);
  for (const child of [...container.children]) {
    if (!keep.has(child)) child.remove();
  }
  let previous = null;
  for (const node of nodes) {
    const expected = previous ? previous.nextElementSibling : container.firstElementChild;
    if (expected !== node) container.insertBefore(node, expected);
    previous = node;
  }
}

// Card del editor con anatomía de KPI: header con tile y hairline, y body con los campos que le tocan al estilo.
// ctx: { onChange(key, value), families }.
export class CardView {
  constructor(card, ctx) {
    this.card = card;
    this.ctx = ctx;
    this.fields = new Map();
    const titleId = `card-${card.id}-title`;
    const fieldList = el("div", { class: "field-list" });
    let contents = [fieldList];
    this.target = fieldList;
    if (card.id === "advanced") {
      const regionId = `adv-${++seq}`;
      const region = el("div", { class: "field-list", id: regionId, hidden: true });
      const toggle = el(
        "button",
        { type: "button", class: "cf-disclosure", "aria-expanded": "false", "aria-controls": regionId },
        el("span", { text: "Mostrar ajustes avanzados" }),
        ico("chevron"),
      );
      toggle.addEventListener("click", () => {
        const open = toggle.getAttribute("aria-expanded") !== "true";
        toggle.setAttribute("aria-expanded", String(open));
        toggle.firstElementChild.textContent = open ? "Ocultar ajustes avanzados" : "Mostrar ajustes avanzados";
        region.hidden = !open;
      });
      contents = [toggle, region];
      this.target = region;
    }
    this.node = el(
      "section",
      { class: "cf-kpi kpi-card", "aria-labelledby": titleId },
      el(
        "header",
        { class: "cf-kpi__head" },
        el("span", { class: `cf-tile cf-tile--${card.tone}` }, ico(card.icon)),
        el("h2", { class: "cf-kpi__title", id: titleId, text: card.title }),
      ),
      el("div", { class: "cf-kpi__rule" }),
      el("div", { class: "cf-kpi__body cf-kpi__body--auto" }, ...contents),
    );
  }

  sync(style) {
    const keys = fieldsFor(this.card.id, style, contextFor());
    for (const key of keys) {
      if (!this.fields.has(key)) this.fields.set(key, createField(key, this.ctx, defOf(key, style)));
    }
    reconcile(this.target, keys.map((key) => this.fields.get(key).node));
    for (const key of keys) this.fields.get(key).update(style);
  }

  // Un error del servidor (422) junto al control de su campo. False si la card no tiene ese campo.
  showError(key, text) {
    const field = this.fields.get(key);
    if (!field) return false;
    field.showError(text);
    return true;
  }
}
