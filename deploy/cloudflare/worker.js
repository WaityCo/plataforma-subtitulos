// Worker del sitio: Cloudflare Workers con assets estáticos. Hace lo que antes hacían _middleware.js y los proxies de
// Pages Functions, porque wrangler 4.151.1 ya no crea proyectos Pages nuevos.
//
// - Puerta de acceso: una contraseña (SITE_PASSWORD) abre una sesión, una cookie HttpOnly firmada con HMAC-SHA256
//   (SESSION_SECRET) que dura 30 días. Solo son públicos la página de acceso y los archivos que usa.
// - /api/* y /fonts/* se reenvían a BACKEND_URL con X-Subs-Key, así la clave nunca llega al navegador. El cuerpo
//   viaja en streaming y las cabeceras de Range, ETag o X-Frame-Time vuelven tal cual.
// - El resto de archivos sale de los assets (ASSETS) solo con sesión.
// - Sin secretos, no deja pasar nada: falla cerrado.

const COOKIE = "subs_session";
const SESSION_SECONDS = 60 * 60 * 24 * 30;
const VERSION = "v1";
const PUBLIC_PATHS = new Set(["/css/tokens.css", "/css/components.css", "/assets/logo.svg"]);
const FAILED_LOGIN_DELAY_MS = 800;
// Cabeceras que no viajan al backend: las de conexión, las que añaden Cloudflare o un proxy, y la cookie de sesión,
// que el backend no necesita. El resto (Range, Content-Type, Content-Length, If-None-Match y las de la subida por
// partes) se reenvía tal cual. Expect: 100-continue lo negocia el Worker con el cliente; reenviado al backend
// rompe las subidas grandes.
const DROPPED_REQUEST_HEADERS = new Set([
  "cookie", "host", "authorization", "connection", "keep-alive", "proxy-authorization", "proxy-authenticate", "te",
  "trailer", "transfer-encoding", "upgrade", "expect", "x-subs-key", "x-real-ip",
]);
const DROPPED_REQUEST_PREFIXES = ["cf-", "x-forwarded-"];
// PUT y DELETE hacen falta para la subida por partes. Cualquier otro método se rechaza en el Worker.
const PROXY_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"];
const HOP_BY_HOP = new Set([
  "connection", "keep-alive", "transfer-encoding", "upgrade", "proxy-authenticate", "proxy-authorization", "te", "trailer", "set-cookie",
]);
const UNAVAILABLE = "El servidor se está reiniciando. Intenta de nuevo en unos segundos.";
// Respuestas con las que Cloudflare avisa de que el túnel o el backend no responden. Un JSON del backend no cuenta:
// sus errores llegan con su detail y pasan tal cual.
const OUTAGE_STATUSES = new Set([502, 503, 504, 520, 521, 522, 523, 530]);
const encoder = new TextEncoder();

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    if (path === "/login") return login(request, env);
    if (path === "/logout") return logout();
    if (PUBLIC_PATHS.has(path)) return env.ASSETS.fetch(request);
    if (!(await hasSession(request, env))) {
      return redirect(`/login?next=${encodeURIComponent(safeNext(path + url.search))}`);
    }
    if (path === "/api" || path.startsWith("/api/")) return proxy(request, env);
    if (path === "/fonts" || path.startsWith("/fonts/")) return proxy(request, env);
    return env.ASSETS.fetch(request);
  },
};

async function proxy(request, env) {
  if (!PROXY_METHODS.includes(request.method)) {
    return new Response(JSON.stringify({ detail: "Método no permitido." }), {
      status: 405,
      headers: { "Content-Type": "application/json; charset=utf-8", Allow: PROXY_METHODS.join(", "), "Cache-Control": "no-store" },
    });
  }
  const backend = (env.BACKEND_URL || "").replace(/\/+$/, "");
  if (!backend || !env.SUBS_API_KEY) {
    console.error("Faltan BACKEND_URL o SUBS_API_KEY en los secretos del Worker.");
    return unavailable(request);
  }
  const url = new URL(request.url);
  const headers = forwardedHeaders(request.headers, env.SUBS_API_KEY);
  // El cuerpo pasa en streaming: no se lee ni se guarda. Cada parte de una subida llega a unos 8 MB.
  const init = { method: request.method, headers, redirect: "manual" };
  if (request.method !== "GET" && request.method !== "HEAD") init.body = request.body;
  let upstream;
  try {
    upstream = await fetch(`${backend}${url.pathname}${url.search}`, init);
  } catch (error) {
    console.error("Backend inaccesible:", error?.message ?? String(error));
    return unavailable(request);
  }
  if (isOutage(upstream)) {
    console.error("Backend sin responder, estado", upstream.status);
    return unavailable(request);
  }
  return relay(upstream, request.method, backend);
}

function forwardedHeaders(incoming, key) {
  const headers = new Headers();
  for (const [name, value] of incoming) {
    const lower = name.toLowerCase();
    if (DROPPED_REQUEST_HEADERS.has(lower) || DROPPED_REQUEST_PREFIXES.some((prefix) => lower.startsWith(prefix))) continue;
    headers.set(name, value);
  }
  headers.set("X-Subs-Key", key);
  return headers;
}

function relay(upstream, method, backend) {
  const headers = new Headers();
  for (const [name, value] of upstream.headers) {
    if (!HOP_BY_HOP.has(name.toLowerCase())) headers.set(name, value);
  }
  // Una redirección del backend no debe revelar la URL del túnel: se devuelve solo la ruta.
  const location = headers.get("location");
  if (location && location.startsWith(backend)) headers.set("location", location.slice(backend.length) || "/");
  const bodiless = method === "HEAD" || upstream.status === 304 || upstream.status === 204;
  return new Response(bodiless ? null : upstream.body, { status: upstream.status, statusText: upstream.statusText, headers });
}

// Cloudflare contesta con HTML cuando el túnel cae; el JSON del backend se deja pasar.
function isOutage(upstream) {
  const type = upstream.headers.get("content-type") || "";
  return OUTAGE_STATUSES.has(upstream.status) && !type.includes("application/json");
}

// Navegación (una pestaña que abre /api/...): página que se reintenta sola. La app recibe JSON con detail.
function unavailable(request) {
  const navegacion = request.method === "GET" && (request.headers.get("accept") || "").includes("text/html");
  if (navegacion) return reconnectingPage();
  return new Response(JSON.stringify({ detail: UNAVAILABLE }), {
    status: 503,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", "Retry-After": "10" },
  });
}

function reconnectingPage() {
  return new Response(`<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow">
  <meta http-equiv="refresh" content="10">
  <title>Reiniciando · Click-Flow Subtítulos</title>
  <link rel="stylesheet" href="/css/tokens.css">
  <link rel="stylesheet" href="/css/components.css">
  <style>
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: var(--cf-color-canvas); color: var(--cf-color-ink); font-family: var(--cf-font-sans); }
    .reinicio { width: min(92vw, 380px); display: grid; gap: 16px; padding: 28px; box-sizing: border-box; }
  </style>
</head>
<body>
  <main class="cf-card reinicio" aria-labelledby="reinicio-titulo" aria-live="polite">
    <div class="cf-brand">
      <img class="cf-brand__logo" src="/assets/logo.svg" width="34" height="34" alt="">
      <div class="cf-brand__text">
        <span class="cf-brand__name">Click-Flow</span>
        <span class="cf-brand__by">Subtítulos</span>
      </div>
    </div>
    <h1 class="t-page" id="reinicio-titulo">El servidor se está reiniciando</h1>
    <p class="t-body">Reintentando en unos segundos…</p>
    <p class="cf-field__hint">Esta página se vuelve a cargar sola cada 10 s.</p>
  </main>
</body>
</html>`, {
    status: 503,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "Retry-After": "10",
      "X-Robots-Tag": "noindex, nofollow",
    },
  });
}

async function login(request, env) {
  if (request.method !== "POST") {
    return loginPage({ next: safeNext(new URL(request.url).searchParams.get("next")) });
  }
  const form = await request.formData();
  const next = safeNext(form.get("next"));
  if (!env.SITE_PASSWORD || !env.SESSION_SECRET) {
    return loginPage({ next, error: "El sitio no está configurado: faltan secretos en el Worker.", status: 500 });
  }
  if (await sameText(String(form.get("password") ?? ""), env.SITE_PASSWORD)) {
    const token = await newSession(env.SESSION_SECRET);
    const headers = new Headers({ Location: next, "Cache-Control": "no-store" });
    headers.append("Set-Cookie", sessionCookie(token));
    return new Response(null, { status: 303, headers });
  }
  await new Promise((resolve) => setTimeout(resolve, FAILED_LOGIN_DELAY_MS));
  return loginPage({ next, error: "Contraseña incorrecta.", status: 401 });
}

function logout() {
  const headers = new Headers({ Location: "/login", "Cache-Control": "no-store" });
  headers.append("Set-Cookie", `${COOKIE}=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Lax`);
  return new Response(null, { status: 302, headers });
}

async function hasSession(request, env) {
  if (!env.SESSION_SECRET) return false;
  const token = readCookie(request.headers.get("cookie"), COOKIE);
  const parts = token ? token.split(".") : [];
  if (parts.length !== 3 || parts[0] !== VERSION) return false;
  const expires = Number(parts[1]);
  if (!Number.isInteger(expires) || expires * 1000 <= Date.now()) return false;
  const signature = fromBase64url(parts[2]);
  if (!signature) return false;
  return crypto.subtle.verify("HMAC", await hmacKey(env.SESSION_SECRET), signature, encoder.encode(`${VERSION}.${parts[1]}`));
}

async function newSession(secret) {
  const expires = Math.floor(Date.now() / 1000) + SESSION_SECONDS;
  const payload = `${VERSION}.${expires}`;
  const signature = await crypto.subtle.sign("HMAC", await hmacKey(secret), encoder.encode(payload));
  return `${payload}.${toBase64url(new Uint8Array(signature))}`;
}

function sessionCookie(token) {
  return `${COOKIE}=${token}; Max-Age=${SESSION_SECONDS}; Path=/; HttpOnly; Secure; SameSite=Lax`;
}

function hmacKey(secret) {
  return crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}

// Compara dos textos en tiempo constante: se comparan sus resúmenes SHA-256, que tienen la misma longitud.
async function sameText(given, expected) {
  const [a, b] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(given)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  const x = new Uint8Array(a);
  const y = new Uint8Array(b);
  let difference = 0;
  for (let i = 0; i < x.length; i++) difference |= x[i] ^ y[i];
  return difference === 0;
}

function readCookie(header, name) {
  if (!header) return null;
  for (const part of header.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return rest.join("=");
  }
  return null;
}

// Solo rutas relativas del propio sitio. Nunca vuelve al login ni a una URL externa.
function safeNext(value) {
  const target = typeof value === "string" ? value : "/";
  const valid =
    target.startsWith("/") &&
    !target.startsWith("//") &&
    !target.includes("\\") &&
    !target.startsWith("/login") &&
    !target.startsWith("/logout");
  return valid ? target : "/";
}

function redirect(location) {
  return new Response(null, { status: 302, headers: { Location: location, "Cache-Control": "no-store" } });
}

function loginPage({ next, error = "", status = 200 }) {
  return new Response(pageHtml(next, error), {
    status,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Robots-Tag": "noindex, nofollow",
      "X-Frame-Options": "DENY",
      "Referrer-Policy": "no-referrer",
    },
  });
}

function pageHtml(next, error) {
  const alert = error ? `<p class="cf-field__hint" role="alert">${escapeHtml(error)}</p>` : "";
  return `<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow">
  <meta name="color-scheme" content="light">
  <title>Acceso · Click-Flow Subtítulos</title>
  <link rel="stylesheet" href="/css/tokens.css">
  <link rel="stylesheet" href="/css/components.css">
  <style>
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: var(--cf-color-canvas); color: var(--cf-color-ink); font-family: var(--cf-font-sans); }
    .acceso { width: min(92vw, 380px); display: grid; gap: 16px; padding: 28px; box-sizing: border-box; }
    .acceso form { display: grid; gap: 12px; }
  </style>
</head>
<body>
  <main class="cf-card acceso" aria-labelledby="acceso-titulo">
    <div class="cf-brand">
      <img class="cf-brand__logo" src="/assets/logo.svg" width="34" height="34" alt="">
      <div class="cf-brand__text">
        <span class="cf-brand__name">Click-Flow</span>
        <span class="cf-brand__by">Subtítulos</span>
      </div>
    </div>
    <h1 class="t-page" id="acceso-titulo">Entrar</h1>
    <p class="t-body">Introduce la contraseña del sitio.</p>
    <form method="post" action="/login">
      <input type="hidden" name="next" value="${escapeHtml(next)}">
      <label class="cf-field">
        <span class="cf-field__label">Contraseña</span>
        <input class="cf-input" type="password" name="password" autocomplete="current-password" required autofocus>
      </label>
      <button class="cf-btn cf-btn--ink" type="submit">Entrar</button>
    </form>
    ${alert}
  </main>
</body>
</html>`;
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

function toBase64url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromBase64url(text) {
  if (!/^[A-Za-z0-9_-]+$/.test(text)) return null;
  const base64 = text.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(text.length / 4) * 4, "=");
  try {
    return Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
  } catch {
    return null;
  }
}
