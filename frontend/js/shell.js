// Shell: búsqueda del menú, proyectos recientes con su estado, menú en móvil y ayuda.
import { api, ApiError } from "./api.js";
import { el, status } from "./dom.js";
import { STATUS, forgetJob, isBusy, readRecent } from "./recents.js";

const REFRESH_MS = 3000;
const MAX_LISTED = 8;
const state = { statuses: new Map(), route: { name: "nuevo" }, timer: 0 };

const sidebar = () => document.getElementById("sidebar");
const isTyping = (target) => target instanceof HTMLElement && target.matches("input, textarea, select, [contenteditable]");

// Mostrar u ocultar el menú en móvil. Al abrir se enfoca el primer enlace; al cerrar, el botón del menú.
function setDrawer(open) {
  const menu = document.getElementById("menu-btn");
  sidebar().classList.toggle("is-open", open);
  document.getElementById("scrim").hidden = !open;
  menu.setAttribute("aria-expanded", String(open));
  if (open) sidebar().querySelector("a, button, input")?.focus();
}

function filterMenu() {
  const query = document.getElementById("search").value.trim().toLowerCase();
  for (const item of sidebar().querySelectorAll("[data-search]")) {
    item.hidden = query !== "" && !item.dataset.search.toLowerCase().includes(query);
  }
}

// Lista de proyectos recientes: nombre del archivo y punto de estado con su texto.
function renderRecent() {
  const host = document.getElementById("recent");
  const items = readRecent().slice(0, MAX_LISTED);
  if (!items.length) {
    host.replaceChildren(el("p", { class: "app__empty t-micro t-muted", text: "Aún no hay proyectos" }));
    return;
  }
  host.replaceChildren(
    ...items.map((item) => {
      const current = state.route.name === "editor" && state.route.id === item.id;
      const job = STATUS[state.statuses.get(item.id)];
      return el(
        "a",
        {
          class: "cf-nav__item app__job",
          href: `#/editor/${item.id}`,
          "data-search": item.name,
          "aria-current": current ? "page" : null,
        },
        el("span", { class: "app__job-name", text: item.name, title: item.name }),
        job ? el("span", { class: "app__job-state" }, status(job.tone, job.label)) : null,
      );
    }),
  );
  filterMenu();
}

// Lee el estado de los recientes. Un 404 significa que el job ya no existe: se quita de la lista.
export async function refreshRecent() {
  clearTimeout(state.timer);
  const items = readRecent().slice(0, MAX_LISTED);
  await Promise.all(
    items.map(async (item) => {
      try {
        const job = await api.job(item.id);
        state.statuses.set(item.id, job.status);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          forgetJob(item.id);
          state.statuses.delete(item.id);
        }
      }
    }),
  );
  renderRecent();
  const busy = [...state.statuses.values()].some(isBusy);
  if (busy) state.timer = setTimeout(refreshRecent, REFRESH_MS);
}

// Marca el enlace de la página actual y cierra el menú móvil.
export function setRoute(route) {
  state.route = route;
  for (const link of sidebar().querySelectorAll("[data-route]")) {
    if (link.dataset.route === route.name) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  setDrawer(false);
  renderRecent();
}

export function initShell() {
  const search = document.getElementById("search");
  const menu = document.getElementById("menu-btn");
  const help = document.getElementById("help-dialog");

  search.addEventListener("input", filterMenu);
  search.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    search.value = "";
    filterMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && !isTyping(event.target)) {
      event.preventDefault();
      if (sidebar().classList.contains("is-open") || window.matchMedia("(min-width: 900px)").matches) search.focus();
      else setDrawer(true);
    }
    if (event.key === "Escape" && sidebar().classList.contains("is-open")) {
      setDrawer(false);
      menu.focus();
    }
  });

  menu.addEventListener("click", () => setDrawer(!sidebar().classList.contains("is-open")));
  document.getElementById("scrim").addEventListener("click", () => {
    setDrawer(false);
    menu.focus();
  });

  document.getElementById("help-btn").addEventListener("click", () => help.showModal());
  help.querySelector("[data-close]").addEventListener("click", () => help.close());
  help.addEventListener("click", (event) => {
    if (event.target === help) help.close();
  });

  renderRecent();
  refreshRecent();
}
