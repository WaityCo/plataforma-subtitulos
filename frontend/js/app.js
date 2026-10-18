// Arranque: carga presets y fuentes, registra las caras, prepara el shell y monta la página del hash.
import { api } from "./api.js";
import { el } from "./dom.js";
import { loadFonts } from "./fonts.js";
import { icon } from "./icons.js";
import { parseRoute } from "./router.js";
import { initShell, setRoute } from "./shell.js";
import { mountEditor } from "./pages/editor.js";
import { mountNuevo } from "./pages/nuevo.js";
import { mountPresets } from "./pages/presets.js";

const view = document.getElementById("view");
const PAGES = { nuevo: mountNuevo, presets: mountPresets, editor: mountEditor };
let context = null;
let dispose = () => {};

function hydrateIcons() {
  for (const node of document.querySelectorAll("[data-icon]")) node.innerHTML = icon(node.dataset.icon);
}

function showLoading() {
  view.replaceChildren(el("div", { class: "page-state" }, el("p", { class: "t-body t-muted", role: "status", text: "Cargando…" })));
}

function showFailure(error) {
  view.replaceChildren(
    el(
      "section",
      { class: "cf-card pad-20" },
      el(
        "div",
        { class: "page-state" },
        el("h1", { class: "t-page", tabindex: "-1", text: "No se pudo conectar con el servidor" }),
        el("p", { class: "t-body t-muted", text: `${error.message} Revisa que el backend esté corriendo en esta máquina.` }),
        el("button", { type: "button", class: "cf-btn cf-btn--ink cf-btn--32", onclick: boot }, "Reintentar"),
      ),
    ),
  );
}

// El límite de subida lo fija el servidor (SUBS_MAX_UPLOAD_MB). El texto de ayuda lo muestra cuando /api/config
// responde; si no responde, no muestra ninguna cifra.
function showUploadHint() {
  api
    .config()
    .then((config) => {
      if (!Number.isFinite(config?.max_upload_mb)) return;
      for (const node of document.querySelectorAll("[data-max-upload-hint]")) {
        node.textContent = `, hasta ${config.max_upload_mb} MB`;
      }
    })
    .catch(() => {});
}

async function boot() {
  showLoading();
  showUploadHint();
  try {
    const [presets, faces] = await Promise.all([api.presets(), api.fonts()]);
    await loadFonts(faces);
    context = { presets };
  } catch (error) {
    showFailure(error);
    return;
  }
  window.addEventListener("hashchange", render);
  render();
}

// Monta la página del hash. La anterior se desmonta antes: sin timers ni peticiones colgadas.
function render() {
  const route = parseRoute();
  dispose();
  dispose = () => {};
  setRoute(route);
  dispose = PAGES[route.name](view, context, route) ?? (() => {});
  window.scrollTo({ top: 0 });
}

hydrateIcons();
initShell();
boot();
