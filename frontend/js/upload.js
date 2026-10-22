// Subida de un video. Con chunk_bytes en /api/config va por trozos (api.js: uploadClient): cada trozo se reintenta
// 3 veces con esperas de 1, 3 y 9 s, y un 4xx (413, 507, 409, 400...) no se reintenta. Sin chunk_bytes, el archivo
// entero va a POST /api/jobs. Los trozos se envían upload_concurrency a la vez (1 desde el Mac, 3 por el túnel).
// Lo subido se guarda en localStorage (subs.uploads): si el mismo archivo se elige otra vez, el servidor dice qué
// trozos tiene y solo se envían los que faltan.
import { ApiError, createJob, uploadClient } from "./api.js";

export const RETRY_DELAYS = [1000, 3000, 9000];
// 520-524 son códigos de Cloudflare (524: el origen no respondió a tiempo): fallos transitorios, como la red.
const RETRYABLE = new Set([0, 408, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524]);
const KEY = "subs.uploads";
const SPEED_WINDOW_MS = 3000;
const MAX_CONCURRENCY = 8; // el mismo tope que el servidor (SUBS_UPLOAD_CONCURRENCY)

// Lo que lanza una subida cancelada. Los demás fallos llegan como ApiError (status 0 si es la red).
export class UploadCancelled extends Error {
  constructor() {
    super("Subida cancelada.");
    this.name = "UploadCancelled";
  }
}

// Espera ms milisegundos. Si la señal se cancela antes, rechaza con UploadCancelled.
export function pause(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new UploadCancelled());
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new UploadCancelled());
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

// Subidas a medias en localStorage: una entrada por archivo, { upload_id, name, size, lastModified, chunk_size }.
// chunk_size va aparte porque GET /api/uploads/{id} no lo devuelve y el servidor lo fija al crear la subida.
// Sin almacenamiento (modo privado) la subida funciona, solo que no se reanuda.
export function uploadStore(storage = globalThis.localStorage) {
  const read = () => {
    try {
      const list = JSON.parse(storage?.getItem(KEY) || "[]");
      return Array.isArray(list) ? list : [];
    } catch {
      return [];
    }
  };
  const write = (list) => {
    try {
      if (list.length) storage.setItem(KEY, JSON.stringify(list));
      else storage.removeItem(KEY);
    } catch {
      // Sin almacenamiento no hay reanudación, pero la subida sigue.
    }
  };
  return {
    find: (file) =>
      read().find((entry) => entry.name === file.name && entry.size === file.size && entry.lastModified === file.lastModified) ?? null,
    save: (entry) => write([...read().filter((item) => item.upload_id !== entry.upload_id), entry]),
    forget: (uploadId) => write(read().filter((item) => item.upload_id !== uploadId)),
  };
}

// Subida a medias de este archivo, o null. La pantalla lo usa para avisar antes de subir.
export const pendingUpload = (file, store = uploadStore()) => store.find(file);

const retryable = (error) => error instanceof ApiError && RETRYABLE.has(error.status);

// Velocidad media de los últimos 3 s (o desde el inicio) y tiempo restante en segundos. Sin velocidad, eta es null.
function meter(total, startBytes, now) {
  const samples = [{ t: now(), bytes: startBytes }];
  return (bytes) => {
    const t = now();
    samples.push({ t, bytes });
    while (samples.length > 2 && t - samples[1].t >= SPEED_WINDOW_MS) samples.shift();
    const base = samples[0];
    const seconds = (t - base.t) / 1000;
    const speed = seconds > 0 ? Math.max(0, (bytes - base.bytes) / seconds) : 0;
    return { speed, eta: speed > 0 ? (total - bytes) / speed : null };
  };
}

// Sube el video y resuelve con { job_id }. onProgress recibe { sent, total, speed, eta } (bytes y segundos);
// onState avisa de la reanudación, de cada reintento y del paso final. deps solo lo usan las pruebas.
export async function sendVideo({ file, preset, language, overrides, config, signal, onProgress = () => {}, onState = () => {} }, deps = {}) {
  const { client = uploadClient, store = uploadStore(), now = () => performance.now(), wait = pause, post = createJob } = deps;
  const chunk = config?.chunk_bytes;

  if (!(Number.isFinite(chunk) && chunk > 0)) {
    // Sin chunk_bytes el backend no admite trozos: el archivo entero va a POST /api/jobs.
    const measure = meter(file.size, 0, now);
    try {
      return await post(
        { file, preset, overrides, language },
        (fraction) => onProgress({ sent: fraction * file.size, total: file.size, ...measure(fraction * file.size) }),
        signal,
      );
    } catch (error) {
      if (signal?.aborted) throw new UploadCancelled();
      throw error;
    }
  }

  // Subida guardada del mismo archivo: el servidor dice qué trozos tiene. Si ya no encaja (404, otro tamaño o
  // otro número de trozos), se descarta y se empieza de nuevo.
  let session = null;
  const saved = store.find(file);
  if (saved) {
    try {
      const state = await client.status(saved.upload_id);
      if (state.size === file.size && state.total_chunks === Math.ceil(file.size / saved.chunk_size)) {
        session = { id: saved.upload_id, size: saved.chunk_size, received: state.received };
      }
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 404)) throw error;
    }
    if (!session) store.forget(saved.upload_id);
  }
  if (!session) {
    const created = await client.start({ filename: file.name, size: file.size, content_type: file.type || "" });
    session = { id: created.upload_id, size: created.chunk_size, received: [] };
    store.save({ upload_id: session.id, name: file.name, size: file.size, lastModified: file.lastModified, chunk_size: session.size });
  }

  const { id, size } = session;
  const count = Math.ceil(file.size / size);
  const length = (n) => Math.min(file.size, (n + 1) * size) - n * size;
  const have = new Set(session.received.filter((n) => n < count));
  const missing = Array.from({ length: count }, (_, n) => n).filter((n) => !have.has(n));
  const concurrency = Math.min(MAX_CONCURRENCY, Math.max(1, Math.floor(Number(config.upload_concurrency) || 1)));
  let finished = [...have].reduce((sum, n) => sum + length(n), 0); // bytes de los trozos ya terminados
  const inFlight = new Map(); // trozo -> bytes enviados de su intento actual
  const measure = meter(file.size, finished, now);
  const report = () => {
    let bytes = finished;
    for (const loaded of inFlight.values()) bytes += loaded;
    onProgress({ sent: bytes, total: file.size, ...measure(bytes) });
  };

  onState({ kind: have.size ? "resume" : "start", done: have.size, total: count });
  report();

  // Cancelar el usuario o un fallo sin reintento para los trozos en curso. Ninguno nuevo empieza después.
  const stop = new AbortController();
  const halt = () => stop.abort();
  if (signal?.aborted) halt();
  else signal?.addEventListener("abort", halt, { once: true });

  async function sendChunk(n) {
    const blob = file.slice(n * size, n * size + length(n));
    for (let attempt = 0; ; attempt += 1) {
      inFlight.set(n, 0);
      try {
        await client.chunk(id, n, blob, { signal: stop.signal, onProgress: (loaded) => { inFlight.set(n, loaded); report(); } });
        break;
      } catch (error) {
        inFlight.delete(n);
        if (signal?.aborted) throw new UploadCancelled();
        // Otro trozo ya ha fallado sin reintento: este se para sin reintentar.
        if (stop.signal.aborted) throw error;
        if (!retryable(error) || attempt === RETRY_DELAYS.length) throw error;
        onState({ kind: "retry", chunk: n, total: count, attempt: attempt + 1, delay: RETRY_DELAYS[attempt], message: error.message });
        await wait(RETRY_DELAYS[attempt], stop.signal);
      }
    }
    inFlight.delete(n);
    finished += length(n);
    report();
  }

  // Cada carril toma el siguiente trozo pendiente. Con concurrency 1 es el envío de uno en uno de siempre.
  let next = 0;
  const lanes = Array.from({ length: Math.min(concurrency, missing.length) }, async () => {
    while (next < missing.length) {
      const n = missing[next];
      next += 1;
      await sendChunk(n);
    }
  });

  try {
    await Promise.all(lanes);
  } catch (error) {
    stop.abort();
    if (error instanceof UploadCancelled) {
      // Cancelar borra la subida en el servidor. No se espera la respuesta: la pantalla ya dice que se canceló.
      store.forget(id);
      client.remove(id).catch(() => {});
    }
    throw error;
  } finally {
    signal?.removeEventListener("abort", halt);
  }

  onState({ kind: "complete" });
  try {
    const body = await client.complete(id, { preset, language: language || null, overrides: overrides ?? null });
    store.forget(id);
    return body;
  } catch (error) {
    // 400: el archivo no es un video y el servidor borra la subida, así que aquí también se olvida.
    // Otros fallos (409 faltan trozos, 507 sin espacio…) dejan la subida guardada para reanudar.
    if (error instanceof ApiError && error.status === 400) store.forget(id);
    throw error;
  }
}
