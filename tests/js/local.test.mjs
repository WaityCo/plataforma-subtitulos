// Pruebas de frontend/js/local.js con el runner de Node (node --test tests/js/). La sonda usa un fetch falso: no hay
// red ni navegador. El pintado del banner (localBanner) necesita el DOM y se verifica en el navegador.
import { test } from "node:test";
import assert from "node:assert/strict";
import { PING_MS, localPing, offerLocal } from "../../frontend/js/local.js";

const BASE = "http://127.0.0.1:8765";
const okJson = (body = { ok: true }) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

function recordingFetch(response) {
  const urls = [];
  const fetchImpl = async (url) => {
    urls.push(url);
    return response(url);
  };
  return { fetchImpl, urls };
}

test("el ping mide 800 ms como máximo", () => {
  assert.equal(PING_MS, 800);
});

test("localPing consulta /api/local-ping y da true con { ok: true }", async () => {
  const { fetchImpl, urls } = recordingFetch(() => okJson());

  assert.equal(await localPing(BASE, { fetchImpl }), true);
  assert.deepEqual(urls, [`${BASE}/api/local-ping`]);
});

test("localPing da false si la conexión se rechaza (no hay servidor en el Mac)", async () => {
  const fetchImpl = async () => {
    throw new TypeError("Failed to fetch");
  };

  assert.equal(await localPing(BASE, { fetchImpl }), false);
});

test("localPing da false con un estado de error, un cuerpo que no es { ok: true } o un texto que no es JSON", async () => {
  const respuestas = [
    () => new Response("no encontrado", { status: 404 }),
    () => okJson({ ok: false }),
    () => new Response("<html>Cloudflare</html>", { status: 200 }),
  ];
  for (const responder of respuestas) {
    const { fetchImpl } = recordingFetch(responder);
    assert.equal(await localPing(BASE, { fetchImpl }), false);
  }
});

test("localPing corta a los timeoutMs si el Mac no contesta", async () => {
  const fetchImpl = (_url, { signal }) =>
    new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(new Error("abortado"))));

  const inicio = Date.now();
  assert.equal(await localPing(BASE, { fetchImpl, timeoutMs: 20 }), false);
  assert.ok(Date.now() - inicio < 500);
});

test("en el propio Mac (localhost, 127.0.0.1 o [::1]) no se ofrece nada y no se consulta el ping", async () => {
  for (const hostname of ["localhost", "127.0.0.1", "[::1]"]) {
    const { fetchImpl, urls } = recordingFetch(() => okJson());
    let shown = false;

    const offered = await offerLocal({ base: BASE, hostname, fetchImpl, show: () => (shown = true) });

    assert.equal(offered, false, hostname);
    assert.equal(shown, false, hostname);
    assert.deepEqual(urls, [], hostname);
  }
});

test("en el sitio público, si el Mac responde, muestra el banner con la URL local", async () => {
  const { fetchImpl } = recordingFetch(() => okJson());
  const mostrados = [];

  const offered = await offerLocal({ base: BASE, hostname: "subtitulos.example.workers.dev", fetchImpl, show: (base) => mostrados.push(base) });

  assert.equal(offered, true);
  assert.deepEqual(mostrados, [BASE]);
});

test("en el sitio público, si el Mac no responde, no muestra nada y no falla", async () => {
  const fetchImpl = async () => {
    throw new TypeError("Failed to fetch");
  };
  const mostrados = [];

  const offered = await offerLocal({ base: BASE, hostname: "subtitulos.example.workers.dev", fetchImpl, show: (base) => mostrados.push(base) });

  assert.equal(offered, false);
  assert.deepEqual(mostrados, []);
});
