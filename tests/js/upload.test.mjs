// Pruebas de frontend/js/upload.js con el runner de Node (node --test tests/js/). Sin navegador: el cliente de la API
// y el almacenamiento son falsos, y las esperas de reintento no esperan de verdad.
import { test } from "node:test";
import assert from "node:assert/strict";
import { ApiError } from "../../frontend/js/api.js";
import { UploadCancelled, sendVideo, uploadStore } from "../../frontend/js/upload.js";

const settle = async () => {
  for (let i = 0; i < 5; i += 1) await new Promise((resolve) => setImmediate(resolve));
};

const fileOf = (size, name = "video.mp4") => ({ name, size, lastModified: 1, type: "video/mp4", slice: (start, end) => ({ start, end }) });

function memoryStorage() {
  const data = new Map();
  return {
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => data.set(key, String(value)),
    removeItem: (key) => data.delete(key),
  };
}

// Cliente falso de la API de trozos. behave({ n, attempt, onProgress }) decide cómo acaba cada intento: una promesa.
// Si la señal se aborta, el intento rechaza con ApiError(0), igual que el cliente real.
function makeClient({ size = 250, chunk = 100, behave = () => Promise.resolve(), status, complete } = {}) {
  const calls = { starts: 0, chunks: [], completed: [], removed: [], maxInFlight: 0 };
  const attempts = new Map();
  let inFlight = 0;
  const client = {
    async start() {
      calls.starts += 1;
      return { upload_id: "u1", chunk_size: chunk, total_chunks: Math.ceil(size / chunk) };
    },
    async status() {
      return status ? status() : { received: [], total_chunks: Math.ceil(size / chunk), size };
    },
    async complete(id, settings) {
      calls.completed.push({ id, settings });
      return complete ? complete() : { job_id: "j1" };
    },
    async remove(id) {
      calls.removed.push(id);
    },
    chunk(id, n, blob, { signal, onProgress } = {}) {
      const attempt = (attempts.get(n) ?? 0) + 1;
      attempts.set(n, attempt);
      calls.chunks.push({ n, attempt });
      inFlight += 1;
      calls.maxInFlight = Math.max(calls.maxInFlight, inFlight);
      return new Promise((resolve, reject) => {
        const end = () => {
          inFlight -= 1;
          signal?.removeEventListener("abort", onAbort);
        };
        const onAbort = () => {
          end();
          reject(new ApiError(0, "Envío cancelado."));
        };
        if (signal?.aborted) return onAbort();
        signal?.addEventListener("abort", onAbort, { once: true });
        Promise.resolve(behave({ n, attempt, onProgress })).then(
          () => {
            end();
            resolve({ chunk: n });
          },
          (error) => {
            end();
            reject(error);
          },
        );
      });
    },
  };
  return { client, calls };
}

// Espera falsa: registra el retraso y respeta la cancelación como pause() de upload.js.
function fakeWaits() {
  const waits = [];
  const wait = async (ms, signal) => {
    waits.push(ms);
    if (signal?.aborted) throw new UploadCancelled();
  };
  return { waits, wait };
}

function depsOf(client, store, wait) {
  return { client, store, now: () => 0, wait };
}

test("con upload_concurrency 1 los trozos van de uno en uno y se completa la subida", async () => {
  const { client, calls } = makeClient({ size: 250, chunk: 100 });
  const { wait } = fakeWaits();
  const store = uploadStore(memoryStorage());

  const body = await sendVideo(
    { file: fileOf(250), preset: "ken_remedie", language: "es", config: { chunk_bytes: 100, upload_concurrency: 1 } },
    depsOf(client, store, wait),
  );

  assert.deepEqual(calls.chunks.map((c) => c.n), [0, 1, 2]);
  assert.equal(calls.maxInFlight, 1);
  assert.deepEqual(calls.completed, [{ id: "u1", settings: { preset: "ken_remedie", language: "es", overrides: null } }]);
  assert.deepEqual(body, { job_id: "j1" });
  assert.equal(store.find(fileOf(250)), null);
});

test("sin upload_concurrency la subida va de uno en uno", async () => {
  const gates = [];
  const { client, calls } = makeClient({ size: 300, chunk: 100, behave: ({ n }) => new Promise((resolve) => (gates[n] = resolve)) });
  const { wait } = fakeWaits();

  const sending = sendVideo({ file: fileOf(300), preset: "p", config: { chunk_bytes: 100 } }, depsOf(client, uploadStore(memoryStorage()), wait));
  await settle();
  assert.deepEqual(calls.chunks.map((c) => c.n), [0]);
  gates[0]();
  await settle();
  gates[1]();
  await settle();
  gates[2]();
  await sending;
  assert.equal(calls.maxInFlight, 1);
});

test("con upload_concurrency 3 envía tres trozos a la vez, nunca más, y avanza al terminar cada uno", async () => {
  const gates = [];
  const { client, calls } = makeClient({ size: 800, chunk: 100, behave: ({ n }) => new Promise((resolve) => (gates[n] = resolve)) });
  const { wait } = fakeWaits();

  const sending = sendVideo(
    { file: fileOf(800), preset: "p", config: { chunk_bytes: 100, upload_concurrency: 3 } },
    depsOf(client, uploadStore(memoryStorage()), wait),
  );
  await settle();
  assert.deepEqual(calls.chunks.map((c) => c.n), [0, 1, 2]);

  gates[1]();
  await settle();
  assert.deepEqual(calls.chunks.map((c) => c.n), [0, 1, 2, 3]);

  for (const n of [0, 3, 2, 4, 5, 6, 7]) {
    await settle();
    gates[n]();
  }
  await sending;

  assert.equal(calls.maxInFlight, 3);
  assert.deepEqual(calls.chunks.map((c) => c.n).sort((a, b) => a - b), [0, 1, 2, 3, 4, 5, 6, 7]);
  assert.equal(calls.completed.length, 1);
});

test("un 503 reintenta ese trozo tras 1 s y los demás siguen sin esperar", async () => {
  const states = [];
  const { client, calls } = makeClient({
    size: 200,
    chunk: 100,
    behave: ({ n, attempt }) => (n === 0 && attempt === 1 ? Promise.reject(new ApiError(503, "Sin servicio")) : Promise.resolve()),
  });
  const { waits, wait } = fakeWaits();

  const body = await sendVideo(
    { file: fileOf(200), preset: "p", config: { chunk_bytes: 100, upload_concurrency: 2 }, onState: (state) => states.push(state) },
    depsOf(client, uploadStore(memoryStorage()), wait),
  );

  assert.deepEqual(waits, [1000]);
  assert.deepEqual(calls.chunks.map((c) => `${c.n}:${c.attempt}`).sort(), ["0:1", "0:2", "1:1"]);
  assert.ok(states.some((s) => s.kind === "retry" && s.chunk === 0 && s.attempt === 1 && s.delay === 1000));
  assert.deepEqual(body, { job_id: "j1" });
});

test("un 413 no se reintenta: para los trozos en curso, no envía más y deja la subida para reanudar", async () => {
  const store = uploadStore(memoryStorage());
  const { client, calls } = makeClient({
    size: 300,
    chunk: 100,
    behave: ({ n }) => (n === 0 ? Promise.reject(new ApiError(413, "Trozo demasiado grande")) : new Promise(() => {})),
  });
  const { waits, wait } = fakeWaits();

  await assert.rejects(
    sendVideo({ file: fileOf(300), preset: "p", config: { chunk_bytes: 100, upload_concurrency: 2 } }, depsOf(client, store, wait)),
    (error) => error instanceof ApiError && error.status === 413,
  );

  assert.deepEqual(waits, []);
  assert.deepEqual(calls.chunks.map((c) => c.n), [0, 1]);
  assert.equal(calls.completed.length, 0);
  assert.deepEqual(calls.removed, []);
  assert.ok(store.find(fileOf(300)));
});

test("cancelar a mitad lanza UploadCancelled, borra la subida en el servidor y olvida lo guardado", async () => {
  const controller = new AbortController();
  const store = uploadStore(memoryStorage());
  const { client, calls } = makeClient({ size: 200, chunk: 100, behave: () => new Promise(() => {}) });
  const { wait } = fakeWaits();

  const sending = sendVideo(
    { file: fileOf(200), preset: "p", config: { chunk_bytes: 100, upload_concurrency: 2 }, signal: controller.signal },
    depsOf(client, store, wait),
  );
  await settle();
  controller.abort();

  await assert.rejects(sending, UploadCancelled);
  await settle();
  assert.deepEqual(calls.removed, ["u1"]);
  assert.equal(store.find(fileOf(200)), null);
  assert.equal(calls.completed.length, 0);
});

test("reanudar: solo se envían los trozos que el servidor no tiene y el progreso empieza con lo ya subido", async () => {
  const storage = memoryStorage();
  const store = uploadStore(storage);
  const file = fileOf(250);
  store.save({ upload_id: "u1", name: file.name, size: file.size, lastModified: file.lastModified, chunk_size: 100 });
  const { client, calls } = makeClient({ size: 250, chunk: 100, status: () => ({ received: [0], total_chunks: 3, size: 250 }) });
  const { wait } = fakeWaits();
  const states = [];
  const progress = [];

  await sendVideo(
    {
      file,
      preset: "p",
      config: { chunk_bytes: 100, upload_concurrency: 3 },
      onState: (state) => states.push(state),
      onProgress: (p) => progress.push(p),
    },
    depsOf(client, store, wait),
  );

  assert.equal(calls.starts, 0);
  assert.deepEqual(calls.chunks.map((c) => c.n), [1, 2]);
  assert.deepEqual(states[0], { kind: "resume", done: 1, total: 3 });
  assert.equal(progress[0].sent, 100);
  assert.equal(calls.completed.length, 1);
  assert.equal(store.find(file), null);
});

test("el progreso suma los bytes de los trozos en curso y acaba en el total", async () => {
  const sent = [];
  const { client } = makeClient({
    size: 200,
    chunk: 100,
    behave: async ({ onProgress }) => {
      onProgress(40);
      onProgress(100);
    },
  });
  const { wait } = fakeWaits();

  await sendVideo(
    { file: fileOf(200), preset: "p", config: { chunk_bytes: 100, upload_concurrency: 2 }, onProgress: (p) => sent.push(p.sent) },
    depsOf(client, uploadStore(memoryStorage()), wait),
  );

  assert.equal(sent.at(-1), 200);
  assert.ok(sent.every((bytes) => bytes <= 200));
});

test("sin chunk_bytes el archivo entero va a POST /api/jobs", async () => {
  const unused = { start: () => Promise.reject(new Error("no debe llamarse")) };
  const post = async (_args, onFraction) => {
    onFraction(0.5);
    return { job_id: "j9" };
  };
  const { wait } = fakeWaits();

  const body = await sendVideo({ file: fileOf(100), preset: "ken", config: {} }, { client: unused, store: uploadStore(memoryStorage()), now: () => 0, wait, post });

  assert.deepEqual(body, { job_id: "j9" });
});

test("un 400 al completar olvida la subida y un 409 la deja guardada", async () => {
  for (const [status, guardada] of [
    [400, false],
    [409, true],
  ]) {
    const store = uploadStore(memoryStorage());
    const { client } = makeClient({ size: 100, chunk: 100, complete: () => Promise.reject(new ApiError(status, "x")) });
    const { wait } = fakeWaits();

    await assert.rejects(
      sendVideo({ file: fileOf(100), preset: "p", config: { chunk_bytes: 100 } }, depsOf(client, store, wait)),
      (error) => error instanceof ApiError && error.status === status,
    );
    assert.equal(store.find(fileOf(100)) !== null, guardada, `estado ${status}`);
  }
});
