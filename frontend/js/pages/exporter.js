// Exportar: render de preview (6 s) o final, con progreso en ticks, resultado y descargas.
import { api, assetUrl, fileUrl, saveFile } from "../api.js";
import { el, messageOf, setTicks, status, ticksBar } from "../dom.js";

// host: la card de exportar. flush() guarda antes el estilo pendiente, para que el render use el último.
export function mountExport(host, { id, flush, hook = () => null }) {
  let alive = true;
  let timer = 0;
  let busy = false;
  let kind = "final";

  const previewButton = el("button", { type: "button", class: "cf-btn cf-btn--white", onclick: () => render(6) }, "Render preview (6 s)");
  const finalButton = el("button", { type: "button", class: "cf-btn cf-btn--ink", onclick: () => render(null) }, "Render final");
  const bar = ticksBar(100, 1);
  bar.setAttribute("aria-labelledby", "export-title");
  const message = el("div", { "aria-live": "polite" });
  const video = el("video", {
    class: "export__video",
    controls: true,
    playsinline: true,
    preload: "metadata",
    "aria-label": "Resultado del render",
  });
  const resultLink = el("a", { class: "cf-btn cf-btn--ink cf-btn--32", href: "#" }, "Descargar MP4");
  // Con otro origen el atributo download no basta: el MP4 se baja como blob (saveFile).
  resultLink.addEventListener("click", (event) => {
    event.preventDefault();
    saveFile(resultLink.dataset.href, resultLink.getAttribute("download")).catch((error) => say("danger", messageOf(error)));
  });
  const result = el("div", { class: "export__result", hidden: true }, video, el("div", { class: "export__links" }, resultLink));
  const assLink = el("a", { class: "cf-btn cf-btn--white cf-btn--32", href: fileUrl(id, "ass") }, "Descargar .ass");
  assLink.addEventListener("click", (event) => {
    event.preventDefault();
    flush()
      .then(() => saveFile(`${fileUrl(id, "ass")}?v=${Date.now()}`, "subtitles.ass"))
      .catch((error) => say("danger", messageOf(error)));
  });

  host.setAttribute("aria-labelledby", "export-title");
  host.replaceChildren(
    el(
      "div",
      { class: "export" },
      el(
        "div",
        { class: "page-head__row" },
        el("h2", { class: "t-card", id: "export-title", text: "Exportar" }),
        el("div", { class: "export__links" }, assLink),
      ),
      el("div", { class: "export__actions" }, previewButton, finalButton),
      el("div", { class: "export__progress" }, bar, message),
      result,
    ),
  );

  function say(tone, text) {
    message.replaceChildren(status(tone, text, "cf-status--ink"));
  }

  function setBusy(on) {
    previewButton.disabled = on;
    finalButton.disabled = on;
    previewButton.classList.toggle("is-saving", on && kind === "preview");
    finalButton.classList.toggle("is-saving", on && kind === "final");
  }

  function finish() {
    busy = false;
    setBusy(false);
  }

  async function render(seconds) {
    if (busy) return;
    busy = true;
    kind = seconds ? "preview" : "final";
    setBusy(true);
    setTicks(bar, 0);
    say("info", seconds ? "Renderizando la preview" : "Renderizando el video final");
    try {
      await flush();
      await api.render(id, seconds, hook());
      poll();
    } catch (error) {
      finish();
      say("danger", messageOf(error));
    }
  }

  // El job pasa a rendering al encolar el render; cuando vuelve a done (o a error), se muestra el resultado.
  async function poll() {
    if (!alive) return;
    try {
      const job = await api.job(id);
      if (!alive) return;
      if (job.status === "rendering") {
        setTicks(bar, job.percent);
        say("info", `Renderizando · ${Math.round(job.percent)} %`);
        timer = setTimeout(poll, 700);
        return;
      }
      finish();
      if (job.status === "done") {
        const url = kind === "preview" ? job.urls.preview : job.urls.output;
        if (!url) {
          say("danger", "El render terminó sin archivo.");
          return;
        }
        setTicks(bar, 100);
        showResult(url, kind);
        say("success", kind === "preview" ? "Preview lista." : "Video final listo.");
        return;
      }
      setTicks(bar, 0);
      say("danger", job.error || "El render no terminó.");
    } catch {
      timer = setTimeout(poll, 1500);
    }
  }

  function showResult(url, which) {
    const href = `${assetUrl(url)}?v=${Date.now()}`;
    video.src = href;
    resultLink.href = href;
    resultLink.dataset.href = href;
    resultLink.setAttribute("download", which === "preview" ? "preview-6s.mp4" : "video-final.mp4");
    resultLink.textContent = which === "preview" ? "Descargar preview" : "Descargar MP4";
    result.hidden = false;
  }

  return () => {
    alive = false;
    clearTimeout(timer);
  };
}
