// Banner de la versión local. En el sitio público, si el Mac que sirve los subtítulos responde en su propio loopback,
// ofrece abrir la versión local (subidas y descargas a velocidad de disco). Sin respuesta no muestra nada: en otra
// máquina no hay servidor en 127.0.0.1, y el fallo es silencioso.
import { el } from "./dom.js";

export const LOCAL_URL = (typeof window !== "undefined" && window.SUBS_LOCAL_URL) || "http://127.0.0.1:8765";
export const PING_MS = 800;
const LOOPBACK = new Set(["localhost", "127.0.0.1", "[::1]"]);

// true solo si el backend de base responde { ok: true } antes de timeoutMs. Cualquier otro caso (conexión rechazada,
// CORS, un navegador que bloquea la petición, tiempo agotado) cuenta como no disponible.
export async function localPing(base, { fetchImpl = fetch, timeoutMs = PING_MS } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(`${base}/api/local-ping`, { signal: controller.signal, cache: "no-store" });
    if (!response.ok) return false;
    const body = await response.json();
    return body?.ok === true;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

// Si la página no es local y el Mac responde, llama a show(base) y resuelve true. En cualquier otro caso resuelve false.
export async function offerLocal({ base = LOCAL_URL, hostname = location.hostname, fetchImpl, show }) {
  if (LOOPBACK.has(hostname)) return false; // la página ya se sirve desde el Mac
  const available = await localPing(base, fetchImpl ? { fetchImpl } : {});
  if (!available) return false;
  show(base);
  return true;
}

// Banner en el estilo del DS: una frase y el enlace a la versión local.
export function localBanner(base) {
  return el(
    "div",
    { class: "app__local", role: "status" },
    el("p", { class: "app__local-text t-body", text: "Estás en el Mac del servidor. Abre la versión local: subidas y descargas instantáneas." }),
    el("a", { class: "cf-btn cf-btn--ink cf-btn--32", href: base }, "Abrir la versión local"),
  );
}
