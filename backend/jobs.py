"""Jobs: estado, cola en SQLite y un único worker en segundo plano.

Flujo: queued -> transcribing -> ready -> rendering -> done. Cualquier paso puede acabar en error.
Un job se transcribe una sola vez: cambiar el estilo o las palabras solo regenera el ASS.
Solo el dueño del lock de la carpeta de datos arranca el worker y marca jobs como interrumpidos. Los demás procesos
reintentan tomar el lock cada TAKEOVER_SECONDS: si el dueño muere, el siguiente toma el worker.
"""

import errno
import fcntl
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import MB, Settings
from . import thumbs
from .media import VideoInfo

logger = logging.getLogger(__name__)

WORDS_FILE = "words.json"
ASS_FILE = "subtitles.ass"
OUTPUT_FILE = "output.mp4"
PARTIAL_OUTPUT_FILE = "output.partial.mp4"
PREVIEW_FILE = "preview.mp4"
PARTIAL_PREVIEW_FILE = "preview.partial.mp4"
RESTART_ERROR = "interrumpido por reinicio"
EDITABLE_STATUSES = ("ready", "done", "error")  # además tiene que existir words.json
ESTADOS_LEGIBLES = {
    "queued": "en cola",
    "transcribing": "transcribiendo",
    "ready": "listo",
    "rendering": "renderizando",
    "done": "terminado",
    "error": "error",
}
SIN_LIBASS = "El quemado no está disponible: el FFmpeg resuelto no tiene libass (filtro 'ass')."
MIN_FREE_BYTES = 500 * MB  # espacio libre mínimo antes de subir o renderizar; con videos grandes manda el triple
JOB_ID = re.compile(r"[0-9a-f]{32}")
LOCK_FILE = "subs.lock"
LOCK_GUARD_FILE = "subs.lock.guard"  # flock que serializa la lectura y escritura del lock entre procesos
HEARTBEAT_SECONDS = 15.0
STALE_AFTER_SECONDS = 120.0
TAKEOVER_SECONDS = 15.0  # sin lock, este proceso reintenta tomarlo con este período
FAIL_WRITE_ATTEMPTS = 3  # con el disco casi lleno, guardar el error puede fallar hasta liberar espacio


class JobError(Exception):
    """Error de dominio. La API lo devuelve como {"detail": ...} con su status_code."""

    status_code = 500


class JobNotFound(JobError):
    status_code = 404


class MissingArtifact(JobError):
    status_code = 404


class JobConflict(JobError):
    status_code = 409


class InvalidStyle(JobError):
    status_code = 422


class InvalidRender(JobError):
    status_code = 422


class BurnUnavailable(JobError):
    status_code = 501


class NoDiskSpace(JobError):
    status_code = 507


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    stage TEXT,
    percent REAL NOT NULL DEFAULT 0,
    error TEXT,
    input_ext TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    duration REAL NOT NULL,
    preset TEXT NOT NULL,
    overrides TEXT,
    language TEXT,
    model_size TEXT NOT NULL,
    hook TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS queue (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    preview_seconds REAL
);
"""


class JobStore:
    """Persistencia en SQLite. Cada operación abre su conexión: simple y seguro entre hilos."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:  # COMMIT al salir, ROLLBACK si hay excepción
                yield conn
        finally:
            conn.close()

    def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_SCHEMA)
            # Bases creadas antes del gancho: los jobs ganan la columna hook y quedan sin gancho guardado.
            if "hook" not in {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}:
                db.execute("ALTER TABLE jobs ADD COLUMN hook TEXT")
            # Bases creadas antes de preview_seconds: la cola gana la columna y conserva sus pasos.
            columns = {row["name"] for row in db.execute("PRAGMA table_info(queue)")}
            if "preview_seconds" not in columns:
                db.execute("ALTER TABLE queue ADD COLUMN preview_seconds REAL")

    def create(self, job: dict[str, Any]) -> None:
        """Inserta el job y su transcripción en la cola, en una sola transacción."""
        columns = ", ".join(job)
        marks = ", ".join("?" for _ in job)
        with self._db() as db:
            db.execute(f"INSERT INTO jobs ({columns}) VALUES ({marks})", tuple(job.values()))
            db.execute("INSERT INTO queue (job_id, kind) VALUES (?, 'transcribe')", (job["id"],))

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def update(self, job_id: str, **fields: Any) -> None:
        assignments = ", ".join(f"{name} = ?" for name in fields)
        with self._db() as db:
            db.execute(
                f"UPDATE jobs SET {assignments}, updated_at = ? WHERE id = ?",
                (*fields.values(), time.time(), job_id),
            )

    def enqueue(self, job_id: str, kind: str, preview_seconds: float | None = None) -> None:
        with self._db() as db:
            db.execute(
                "INSERT INTO queue (job_id, kind, preview_seconds) VALUES (?, ?, ?)",
                (job_id, kind, preview_seconds),
            )

    def pop_next(self) -> dict[str, Any] | None:
        """Saca el siguiente paso de la cola, en orden de llegada."""
        with self._db() as db:
            row = db.execute("SELECT seq, job_id, kind, preview_seconds FROM queue ORDER BY seq LIMIT 1").fetchone()
            if row is None:
                return None
            db.execute("DELETE FROM queue WHERE seq = ?", (row["seq"],))
        return dict(row)

    def recover_interrupted(self) -> int:
        """Marca como error lo que estaba en curso. Solo lo llama el dueño del lock: lo que no tiene
        dueño vivo ya no tiene worker. Los 'queued' siguen en cola."""
        with self._db() as db:
            cursor = db.execute(
                "UPDATE jobs SET status = 'error', error = ?, updated_at = ? "
                "WHERE status IN ('transcribing', 'rendering')",
                (RESTART_ERROR, time.time()),
            )
            db.execute("DELETE FROM queue WHERE job_id NOT IN (SELECT id FROM jobs WHERE status = 'queued')")
        return cursor.rowcount


def normalize_words(items: Any) -> list[dict[str, Any]]:
    """Forma que expone la API: text, start, end y emph (true, false o None, que es automático)."""
    if isinstance(items, dict):  # por si el motor envuelve la lista
        items = items.get("words", [])
    return [_word(w) for w in items]


def _word(w: dict[str, Any]) -> dict[str, Any]:
    emph = w.get("emph")
    return {
        "text": str(w["text"]),
        "start": float(w["start"]),
        "end": float(w["end"]),
        "emph": emph if isinstance(emph, bool) else None,
    }


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _dump_json(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _load_json(text: str | None) -> Any:
    return None if text is None else json.loads(text)


def estado_legible(status: str) -> str:
    """Nombre en español de un estado de job, para los mensajes de la API."""
    return ESTADOS_LEGIBLES.get(status, "desconocido")


def espacio_libre(path: Path) -> int:
    """Bytes libres del volumen donde está path."""
    return shutil.disk_usage(path).free


def mensaje_sin_espacio(free_bytes: int) -> str:
    return f"No hay espacio suficiente en disco (quedan {free_bytes // MB} MB). Libera espacio y vuelve a intentarlo."


def error_de_espacio(path: Path) -> NoDiskSpace:
    """Error 507 con el espacio que queda ahora en el volumen de path."""
    return NoDiskSpace(mensaje_sin_espacio(espacio_libre(path)))


def comprobar_espacio(path: Path, input_bytes: int) -> None:
    """Lanza NoDiskSpace si quedan menos de max(500 MB, 3 × input_bytes). El triple cubre la copia del video, su
    transcripción y el quemado."""
    free = espacio_libre(path)
    if free < max(MIN_FREE_BYTES, 3 * input_bytes):
        raise NoDiskSpace(mensaje_sin_espacio(free))


def es_falta_de_espacio(exc: BaseException) -> bool:
    """True si el error viene de un disco lleno: ENOSPC del sistema o el texto que devuelve FFmpeg."""
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return True
    return "No space left on device" in str(exc)


def _tamano(path: Path) -> int:
    return path.stat().st_size if path.is_file() else 0


def _lock_text() -> str:
    return json.dumps({"pid": os.getpid(), "timestamp": time.time()})


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # existe, pero es de otro usuario
        return True
    return True


class DataDirLock:
    """Lock de la carpeta de datos (data/subs.lock) con el pid y una marca de tiempo.

    Un lock es válido si su pid sigue vivo y su marca tiene menos de stale_after segundos. El dueño renueva la marca
    con refresh(). Cada lectura y escritura del lock va bajo un flock sobre data/subs.lock.guard: dos procesos que
    intentan tomar el mismo lock caducado no pueden quedarse los dos con él. Solo el dueño de un lock válido puede
    recuperar jobs.
    """

    def __init__(self, data_dir: Path, stale_after: float = STALE_AFTER_SECONDS) -> None:
        self.path = data_dir / LOCK_FILE
        self.guard_path = data_dir / LOCK_GUARD_FILE
        self.stale_after = stale_after
        self.owned = False

    def acquire(self) -> bool:
        """True si este proceso queda como dueño. False si otro proceso tiene un lock válido."""
        with self._guard():
            holder = self.read()
            if holder is not None and holder["pid"] != os.getpid() and self._valid(holder):
                return False
            self._write()
            self.owned = True
            return True

    def refresh(self) -> bool:
        """Renueva la marca de tiempo. False si el lock ya es de otro proceso: el nuestro caducó y alguien lo tomó."""
        if not self.owned:
            return False
        with self._guard():
            holder = self.read()
            if holder is not None and holder["pid"] != os.getpid():
                self.owned = False
                return False
            self._write()
        return True

    def release(self) -> None:
        """Quita el lock, pero solo si sigue siendo nuestro."""
        if not self.owned:
            return
        with self._guard():
            holder = self.read()
            if holder is not None and holder["pid"] == os.getpid():
                self.path.unlink(missing_ok=True)
        self.owned = False

    def read(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if isinstance(data, dict) and isinstance(data.get("pid"), int) and isinstance(data.get("timestamp"), (int, float)):
            return data
        return None

    def _write(self) -> None:
        _atomic_write(self.path, _lock_text())

    @contextmanager
    def _guard(self) -> Iterator[None]:
        fd = os.open(self.guard_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)  # espera a otro proceso; el kernel suelta el flock si ese proceso muere
            yield
        finally:
            os.close(fd)

    def _valid(self, holder: dict[str, Any]) -> bool:
        return _pid_alive(holder["pid"]) and time.time() - holder["timestamp"] < self.stale_after


class JobManager:
    """Reglas de los jobs: alta, estado, edición de estilo y palabras, y cola de trabajo.

    Solo el dueño del lock arranca el worker. Un segundo proceso sirve la API sobre la misma cola y reintenta tomar el
    lock cada takeover_seconds: si el dueño muere, toma el worker, recupera lo interrumpido y procesa la cola.
    """

    def __init__(
        self,
        settings: Settings,
        engine: Any,
        lock_stale_after: float = STALE_AFTER_SECONDS,
        takeover_seconds: float = TAKEOVER_SECONDS,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
        on_owner: Callable[[], None] | None = None,
    ) -> None:
        self.settings = settings
        self.data_dir = settings.data_dir
        self.jobs_dir = self.data_dir / "jobs"
        self.engine = engine
        self.store = JobStore(self.data_dir / "jobs.db")
        self.dir_lock = DataDirLock(self.data_dir, stale_after=lock_stale_after)
        self.takeover_seconds = takeover_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.owner = False
        self._on_owner = on_owner  # se llama al tomar el worker: al arrancar o tras un relevo
        self._lock = threading.RLock()  # serializa cambios de estado y escrituras del ASS
        self._wake = threading.Event()
        self._stop = threading.Event()  # cierre del proceso
        self._term: threading.Event | None = None  # fin del mandato de dueño actual: cierre o pérdida del lock
        self._worker: threading.Thread | None = None
        self._heartbeat: threading.Thread | None = None
        self._standby: threading.Thread | None = None

    # Ciclo de vida

    def start(self) -> None:
        """Prepara carpetas y BD. Si el lock está libre, este proceso es el dueño: recupera lo interrumpido y arranca
        el worker. Si no, sirve la API y reintenta tomar el lock cada takeover_seconds."""
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        ignore = self.data_dir / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n!.gitignore\n", encoding="utf-8")  # data/ queda fuera de git
        self.store.init()
        self._stop.clear()
        if not self._take_over():
            holder = self.dir_lock.read() or {}
            logger.warning(
                "%s la usa otro proceso (pid %s): no se tocan sus jobs. Se reintentará tomar el worker cada %g s.",
                self.data_dir,
                holder.get("pid", "?"),
                self.takeover_seconds,
            )
        self._standby = threading.Thread(target=self._standby_loop, name="subs-standby", daemon=True)
        self._standby.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._term is not None:
            self._term.set()
        if self._standby is not None:
            self._standby.join(timeout=10)  # antes que el worker: así no toma el lock mientras cerramos
        for thread in (self._worker, self._heartbeat):
            if thread is not None:
                # Un job en curso no se cancela. Si sigue vivo al salir, el siguiente dueño lo marcará.
                thread.join(timeout=10)
        self.dir_lock.release()
        self.owner = False

    def _take_over(self) -> bool:
        """Toma el lock si está libre. Si lo consigue, recupera lo interrumpido y arranca worker y latido."""
        if self._stop.is_set():
            return False
        if self._worker is not None and self._worker.is_alive():
            return False  # el worker del mandato anterior aún termina un job: no se arrancan dos
        if not self.dir_lock.acquire():
            return False
        interrupted = self.store.recover_interrupted()
        if interrupted:
            logger.warning("%d job(s) interrumpidos por el reinicio", interrupted)
        self._term = threading.Event()
        self._worker = threading.Thread(target=self._run, args=(self._term,), name="subs-worker", daemon=True)
        self._heartbeat = threading.Thread(target=self._beat, args=(self._term,), name="subs-lock", daemon=True)
        self.owner = True
        self._worker.start()
        self._heartbeat.start()
        self._wake.set()
        logger.info("Este proceso es el dueño de %s: worker en marcha.", self.data_dir)
        self._avisar_dueno()
        return True

    def _avisar_dueno(self) -> None:
        """Avisa de que este proceso ejecuta los jobs, p. ej. para precargar el modelo. Un fallo no para el worker."""
        if self._on_owner is None:
            return
        try:
            self._on_owner()
        except Exception:
            logger.warning("El aviso de dueño falló; el worker sigue en marcha.", exc_info=True)

    def _standby_loop(self) -> None:
        """Sin lock, reintenta tomarlo cada takeover_seconds. Con lock, no hace nada hasta que lo pierda."""
        while not self._stop.wait(self.takeover_seconds):
            if not self.owner:
                self._take_over()

    def _beat(self, term: threading.Event) -> None:
        """Renueva la marca del lock. Si otro proceso lo tomó, este mandato termina y el worker deja de procesar."""
        while not term.wait(self.heartbeat_seconds):
            if self._stop.is_set():
                return
            if not self.dir_lock.refresh():
                logger.error("Otro proceso tomó el lock de %s: este proceso deja de procesar jobs.", self.data_dir)
                self.owner = False
                term.set()
                return

    # Consultas y altas

    def job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id

    def list_presets(self) -> list[dict[str, Any]]:
        return self.engine.list_presets()

    def list_fonts(self) -> list[Any]:
        return self.engine.font_catalog()

    def validate_style(self, preset: str, overrides: dict[str, Any] | None) -> dict[str, Any]:
        try:
            return self.engine.resolve_style(preset, overrides)
        except ValueError as exc:
            raise InvalidStyle(str(exc)) from exc

    def create_job(
        self,
        *,
        job_id: str,
        input_ext: str,
        info: VideoInfo,
        preset: str,
        overrides: dict[str, Any] | None,
        language: str | None,
        model_size: str,
    ) -> None:
        now = time.time()
        self.store.create(
            {
                "id": job_id,
                "status": "queued",
                "stage": None,
                "percent": 0.0,
                "error": None,
                "input_ext": input_ext,
                "width": info.width,
                "height": info.height,
                "duration": info.duration,
                "preset": preset,
                "overrides": _dump_json(overrides),
                "language": language,
                "model_size": model_size,
                "created_at": now,
                "updated_at": now,
            }
        )
        self._wake.set()

    def get_status(self, job_id: str) -> dict[str, Any]:
        job = self._require(job_id)
        folder = self.job_dir(job_id)
        return {
            "status": job["status"],
            "stage": job["stage"],
            "percent": job["percent"],
            "error": job["error"],
            "video": {"width": job["width"], "height": job["height"], "duration": job["duration"]},
            "preset": job["preset"],
            "overrides": _load_json(job["overrides"]),
            "hook": _load_json(job["hook"]),
            "urls": {
                "input": f"/api/jobs/{job_id}/input",
                "words": f"/api/jobs/{job_id}/words" if (folder / WORDS_FILE).is_file() else None,
                "ass": f"/api/jobs/{job_id}/ass" if (folder / ASS_FILE).is_file() else None,
                "output": f"/api/jobs/{job_id}/output" if (folder / OUTPUT_FILE).is_file() else None,
                "preview": f"/api/jobs/{job_id}/preview" if (folder / PREVIEW_FILE).is_file() else None,
            },
        }

    def input_path(self, job_id: str) -> Path:
        job = self._require(job_id)
        return self.artifact(job_id, f"input{job['input_ext']}")

    def artifact(self, job_id: str, name: str) -> Path:
        self._require(job_id)
        path = self.job_dir(job_id) / name
        if not path.is_file():
            raise MissingArtifact(f"Todavía no existe {name} para este job.")
        return path

    def read_words(self, job_id: str) -> list[dict[str, Any]]:
        return normalize_words(json.loads(self.artifact(job_id, WORDS_FILE).read_text(encoding="utf-8")))

    # Ediciones: nunca vuelven a transcribir

    def update_style(self, job_id: str, preset: str, overrides: dict[str, Any] | None) -> dict[str, Any]:
        self._require(job_id)
        style = self.validate_style(preset, overrides)
        with self._lock:
            job = self._require(job_id)
            self._require_editable(job)
            words = self.read_words(job_id)
            ass = self.engine.build_ass(words, style, job["width"], job["height"])
            _atomic_write(self.job_dir(job_id) / ASS_FILE, ass)
            self.store.update(job_id, preset=preset, overrides=_dump_json(overrides))
        return style

    def update_words(self, job_id: str, words: list[dict[str, Any]]) -> list[dict[str, Any]]:
        clean = normalize_words(words)
        with self._lock:
            job = self._require(job_id)
            self._require_editable(job)
            style = self.validate_style(job["preset"], _load_json(job["overrides"]))
            ass = self.engine.build_ass(clean, style, job["width"], job["height"])  # antes de escribir nada
            folder = self.job_dir(job_id)
            _atomic_write(folder / WORDS_FILE, json.dumps(clean, ensure_ascii=False))
            _atomic_write(folder / ASS_FILE, ass)
            thumbs.invalidate(folder)  # las miniaturas mostraban las palabras anteriores
        return clean

    def request_render(self, job_id: str, preview_seconds: float | None, hook: dict[str, Any] | None = None) -> None:
        """Encola el quemado. Con hook, reemplaza y guarda el gancho del job; sin él, usa el que ya está guardado."""
        self._require(job_id)
        if preview_seconds is not None and preview_seconds > self.settings.max_preview_seconds:
            raise InvalidRender(f"preview_seconds no puede ser mayor que {self.settings.max_preview_seconds:g}.")
        if not self.engine.burn_available():
            raise BurnUnavailable(SIN_LIBASS)
        with self._lock:
            job = self._require(job_id)
            self._require_editable(job)
            if not (self.job_dir(job_id) / ASS_FILE).is_file():
                raise JobConflict("Faltan los subtítulos del job: no hay nada que quemar.")
            comprobar_espacio(self.data_dir, _tamano(self.job_dir(job_id) / f"input{job['input_ext']}"))
            fields: dict[str, Any] = {"status": "rendering", "stage": "burn", "percent": 0.0, "error": None}
            if hook is not None:
                fields["hook"] = _dump_json(hook)
            self.store.update(job_id, **fields)
            self.store.enqueue(job_id, "render", preview_seconds)
        self._wake.set()

    def update_hook(self, job_id: str, hook: dict[str, Any] | None) -> dict[str, Any] | None:
        """Guarda el gancho del job sin renderizar. None lo quita. Como PUT /style, solo si el job es editable."""
        with self._lock:
            job = self._require(job_id)
            self._require_editable(job)
            self.store.update(job_id, hook=_dump_json(hook))
        return hook

    def preview_frame(
        self, job_id: str, preset: str | None, overrides: dict[str, Any] | None, at: float | None, width: int
    ) -> thumbs.Frame:
        """Fotograma del video con los subtítulos del preset (o del estilo guardado) en el instante at, o en el
        automático. Si la misma miniatura ya existe, la devuelve de la caché."""
        job = self._require(job_id)
        if not self.engine.burn_available():
            raise BurnUnavailable(SIN_LIBASS)  # como el render: el fotograma con subtítulos necesita libass
        if job["status"] not in ("ready", "done"):
            raise JobConflict(f"El job no está listo para miniaturas (estado: '{estado_legible(job['status'])}').")
        if preset is None and overrides is None:
            preset, overrides = job["preset"], _load_json(job["overrides"])
        else:
            preset = preset or job["preset"]
        style = self.validate_style(preset, overrides)  # 422, igual que PUT /style
        duration, video_w, video_h = job["duration"], job["width"], job["height"]
        if at is not None and not 0 <= at < duration:
            raise thumbs.InvalidFrame(f"t debe estar entre 0 y {duration:.3f} s.")
        has_words = (self.job_dir(job_id) / WORDS_FILE).is_file()
        words = self.read_words(job_id) if has_words else []
        ass_text = self.engine.build_ass(words, style, video_w, video_h) if words else None
        hook = _load_json(job["hook"])
        if at is None:
            segments = self.engine.build_segments(words, style, video_w, video_h) if words else []
            # Con gancho, el automático evita su tramo si hay segmentos después de su duración.
            at = thumbs.pick_time(segments, duration, style, hook_end=hook["duration_s"] if hook else None)
        at = thumbs.clamp_time(at, duration)
        frame_hook = hook if hook is not None and at < hook["duration_s"] else None  # el gancho dura duration_s
        key = thumbs.cache_key(
            job_id=job_id, preset=preset, overrides=overrides, time=at, width=width, ass_text=ass_text,
            hook=frame_hook,
        )
        folder = self.job_dir(job_id) / thumbs.THUMBS_DIR
        path = folder / f"{key}.jpg"
        if not path.is_file():
            folder.mkdir(parents=True, exist_ok=True)
            thumbs.render_frame(
                self.job_dir(job_id) / f"input{job['input_ext']}", ass_text, at, width, path,
                hook=frame_hook, video_size=(video_w, video_h),
            )
        return thumbs.Frame(path=path, key=key, time=at, empty=not words)

    def segments(self, job_id: str, preset: str | None = None, overrides: dict[str, Any] | None = None) -> list[Any]:
        """Segmentos de los subtítulos. Sin preset ni overrides, usa el estilo guardado del job. Con alguno,
        usa el que pida la consulta (el preset del job si falta) y no guarda nada."""
        job = self._require(job_id)
        if preset is None and overrides is None:
            preset, overrides = job["preset"], _load_json(job["overrides"])
        else:
            preset = preset or job["preset"]
        style = self.validate_style(preset, overrides)  # 422, igual que PUT /style
        if not (self.job_dir(job_id) / WORDS_FILE).is_file():
            raise JobConflict(f"El job todavía no tiene palabras (estado: '{estado_legible(job['status'])}').")
        return self.engine.build_segments(self.read_words(job_id), style, job["width"], job["height"])

    def _require(self, job_id: str) -> dict[str, Any]:
        job = self.store.get(job_id) if JOB_ID.fullmatch(job_id) else None
        if job is None:
            raise JobNotFound("Job no encontrado.")
        return job

    def _require_editable(self, job: dict[str, Any]) -> None:
        has_words = (self.job_dir(job["id"]) / WORDS_FILE).is_file()
        if job["status"] not in EDITABLE_STATUSES or not has_words:
            raise JobConflict(f"El job no admite este cambio en estado '{estado_legible(job['status'])}'.")

    # Worker

    def _run(self, term: threading.Event) -> None:
        """Procesa la cola mientras dure este mandato de dueño: hasta el cierre o hasta perder el lock."""
        while not (term.is_set() or self._stop.is_set()):
            try:
                item = self.store.pop_next()
                if item is None:
                    self._wake.wait(timeout=1.0)
                    self._wake.clear()
                    continue
                if item["kind"] == "transcribe":
                    self._transcribe(item["job_id"])
                else:
                    self._render(item["job_id"], item["preview_seconds"])
            except Exception:  # un fallo puntual no debe matar el worker
                logger.exception("Error en el worker; reintento en 1 s")
                term.wait(1.0)

    def _transcribe(self, job_id: str) -> None:
        job = self.store.get(job_id)
        folder = self.job_dir(job_id)
        self.store.update(job_id, status="transcribing", stage="audio", percent=0.0, error=None)
        try:
            self.engine.transcribe(
                video_path=folder / f"input{job['input_ext']}",
                job_dir=folder,
                preset=job["preset"],
                overrides=_load_json(job["overrides"]),
                language=job["language"],
                model_size=job["model_size"],
                progress=self._progress(job_id),
            )
            missing = [name for name in (WORDS_FILE, ASS_FILE) if not (folder / name).is_file()]
            if missing:
                raise RuntimeError(f"El motor no generó: {', '.join(missing)}.")
        except Exception as exc:
            self._fail(job_id, exc)
            return
        self.store.update(job_id, status="ready", stage=None, percent=100.0, error=None)

    def _render(self, job_id: str, preview_seconds: float | None) -> None:
        """Quema el ASS ya generado. Con preview_seconds, el resultado es preview.mp4 y no output.mp4."""
        job = self.store.get(job_id)
        folder = self.job_dir(job_id)
        if preview_seconds is None:
            partial, final = folder / PARTIAL_OUTPUT_FILE, folder / OUTPUT_FILE
        else:
            partial, final = folder / PARTIAL_PREVIEW_FILE, folder / PREVIEW_FILE
        partial.unlink(missing_ok=True)
        try:
            self.engine.burn(
                video_path=folder / f"input{job['input_ext']}",
                ass_path=folder / ASS_FILE,
                output_path=partial,
                preview_seconds=preview_seconds,
                progress=self._progress(job_id),
                hook=_load_json(job["hook"]),
                width=job["width"],
                height=job["height"],
            )
            if not partial.is_file():
                raise RuntimeError("El quemado terminó sin generar el MP4.")
            os.replace(partial, final)
        except Exception as exc:
            partial.unlink(missing_ok=True)
            self._fail(job_id, exc)
            return
        self.store.update(job_id, status="done", stage=None, percent=100.0, error=None)

    def _progress(self, job_id: str) -> Callable[[str, float], None]:
        """Callback del motor: guarda stage y percent sin escribir en cada tick. El progreso es secundario: si la base
        no admite la escritura (disco lleno), se pierde sin cortar el motor, para que llegue su error real."""
        last: tuple[str, int] | None = None

        def report(stage: str, percent: float) -> None:
            nonlocal last
            value = min(100.0, max(0.0, float(percent)))
            key = (stage, int(value))
            if key == last:
                return
            last = key
            try:
                self.store.update(job_id, stage=stage, percent=value)
            except sqlite3.Error:
                logger.debug("No se guardó el progreso del job %s", job_id, exc_info=True)

        return report

    def _fail(self, job_id: str, exc: BaseException) -> None:
        message = str(exc) or type(exc).__name__
        if es_falta_de_espacio(exc):
            message = mensaje_sin_espacio(espacio_libre(self.data_dir))
        logger.error("Job %s con error: %s", job_id, message, exc_info=exc)
        for _ in range(FAIL_WRITE_ATTEMPTS):  # con el disco casi lleno, la escritura puede fallar hasta liberar espacio
            try:
                self.store.update(job_id, status="error", error=message[:2000])
                return
            except sqlite3.Error:
                self._stop.wait(1.0)
        logger.error("No se pudo guardar el error del job %s", job_id)
