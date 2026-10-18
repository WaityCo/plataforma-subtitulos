// Cliente de /api. Errores según el contrato: JSON {detail} con 400, 404, 409, 413, 422, 501, 503 y 507.
// Base del backend: window.SUBS_API_BASE (config.js). "" = mismo origen. Con otro origen (Cloudflare Pages) las peticiones
// van con credenciales, y el backend tiene que responder CORS para el origen del frontend.
export const API_BASE = String((typeof window !== "undefined" && window.SUBS_API_BASE) || "").replace(/\/+$/, "");
const API = `${API_BASE}/api`;
const PAGE = typeof location !== "undefined" ? location.href : "http://localhost/";
const CROSS_ORIGIN = new URL(API_BASE || PAGE, PAGE).origin !== new URL(PAGE).origin;
const CREDENTIALS = CROSS_ORIGIN ? "include" : "same-origin";

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

// FastAPI puede devolver detail como texto o como lista de errores de validación.
function detailOf(body, fallback) {
  if (body && typeof body.detail === "string") return body.detail;
  if (body && Array.isArray(body.detail)) return body.detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
  return fallback;
}

function parse(text) {
  try {
    return text ? JSON.parse(text) : null;
  } catch {
    return null;
  }
}

// Ruta que devuelve la API (job.urls, p. ej. /api/jobs/{id}/output) en la base del backend.
export const assetUrl = (path) => (path.startsWith("/") ? `${API_BASE}${path}` : path);

async function request(method, path, { body, query } = {}) {
  const url = API + path + (query ? `?${new URLSearchParams(query)}` : "");
  const init = { method, headers: {}, credentials: CREDENTIALS };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new ApiError(0, "No se pudo conectar con el servidor.");
  }
  const data = parse(await response.text());
  if (!response.ok) throw new ApiError(response.status, detailOf(data, `Error ${response.status} del servidor.`));
  return data;
}

export const api = {
  presets: () => request("GET", "/presets"),
  fonts: () => request("GET", "/fonts"),
  // Límites del backend: max_upload_bytes y max_upload_mb. Si el endpoint no responde, el llamador no muestra ninguna cifra.
  config: () => request("GET", "/config"),
  job: (id) => request("GET", `/jobs/${id}`),
  words: (id) => request("GET", `/jobs/${id}/words`),
  saveWords: (id, words) => request("PUT", `/jobs/${id}/words`, { body: words }),
  saveStyle: (id, preset, overrides) => request("PUT", `/jobs/${id}/style`, { body: { preset, overrides } }),
  // Gancho del job: la especificación, o null para quitarlo. Los errores llevan detail (422).
  saveHook: (id, hook) => request("PUT", `/jobs/${id}/hook`, { body: hook }),
  // Sin preset: segmentos del estilo guardado. Con preset: vista previa con ese estilo, sin guardar nada.
  segments: (id, preview) =>
    request("GET", `/jobs/${id}/segments`, {
      query: preview ? { preset: preview.preset, overrides: JSON.stringify(preview.overrides ?? {}) } : undefined,
    }),
  // hook: gancho de apertura (ver hook.js). El backend todavía no lo quema, pero el cuerpo ya lo lleva.
  render: (id, previewSeconds, hook) =>
    request("POST", `/jobs/${id}/render`, { body: { preview_seconds: previewSeconds, ...(hook ? { hook } : {}) } }),
  // Cuadro del video con el preset quemado por libass. X-Frame-Time dice el segundo del cuadro; el blob sirve de src.
  previewFrame: async (id, preset, width) => {
    const url = `${API}/jobs/${id}/preview-frame?${new URLSearchParams({ preset, w: String(width) })}`;
    let response;
    try {
      response = await fetch(url, { credentials: CREDENTIALS });
    } catch {
      throw new ApiError(0, "No se pudo conectar con el servidor.");
    }
    if (!response.ok) throw new ApiError(response.status, detailOf(parse(await response.text()), `Miniatura ${response.status}.`));
    const time = Number(response.headers.get("X-Frame-Time"));
    return { src: URL.createObjectURL(await response.blob()), time: Number.isFinite(time) ? time : null };
  },
};

// URL de un artefacto del job (input, ass, output o preview). El backend sirve Range para <video>.
export const fileUrl = (id, kind) => `${API}/jobs/${id}/${kind}`;

// Descarga un archivo del backend (MP4 o .ass) con su nombre. El atributo download solo funciona en el mismo origen:
// con otro origen el archivo se baja como blob y se guarda desde el navegador.
export async function saveFile(url, name) {
  let response;
  try {
    response = await fetch(url, { credentials: CREDENTIALS });
  } catch {
    throw new ApiError(0, "No se pudo conectar con el servidor.");
  }
  if (!response.ok) throw new ApiError(response.status, detailOf(parse(await response.text()), `Error ${response.status} al descargar.`));
  const objectUrl = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = name;
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
}

// Sube el video con XMLHttpRequest para tener progreso de subida (fetch no lo expone).
// onProgress recibe una fracción de 0 a 1. Resuelve con { job_id }. Con otro origen, la petición lleva credenciales.
export function createJob({ file, preset, overrides, language }, onProgress) {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    form.append("preset", preset);
    if (overrides && Object.keys(overrides).length) form.append("overrides", JSON.stringify(overrides));
    if (language) form.append("language", language);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API}/jobs`);
    xhr.withCredentials = CROSS_ORIGIN;
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      const body = parse(xhr.responseText);
      if (xhr.status === 201) resolve(body);
      else reject(new ApiError(xhr.status, detailOf(body, `Error ${xhr.status} al subir el video.`)));
    };
    xhr.onerror = () => reject(new ApiError(0, "No se pudo conectar con el servidor."));
    xhr.send(form);
  });
}
