"""Subida por partes. El cliente describe el archivo, manda trozos de SUBS_CHUNK_MB, cada uno en su propia petición
(Cloudflare Free corta cada petición en 100 MB), y al completar el servidor arma input.<ext> sin cargar nada en memoria.
Cada subida vive en data/uploads/<id>/ hasta que se completa, se cancela (DELETE) o pasan 24 h sin actividad."""

import json
import logging
import math
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from . import jobs
from .config import MB, Settings
from .jobs import MIN_FREE_BYTES, JobError, NoDiskSpace, mensaje_sin_espacio
from .media import validate_upload

logger = logging.getLogger(__name__)

UPLOADS_DIR = "uploads"
META_FILE = "meta.json"
CHUNKS_DIR = "chunks"
ARMANDO = ".armando"  # sufijo de la carpeta mientras se arma el video: solo una petición de completar la tiene
BORRANDO = ".borrando"  # sufijo de una subida que se cancela: ya nadie la ve, y la limpieza quita lo que quede
ARMANDO_EN_CURSO_SECONDS = 10 * 60  # un armado sin actividad en este tiempo se da por cortado
MAX_AGE_SECONDS = 24 * 3600
CLEAN_EVERY_SECONDS = 3600
MARGIN_BYTES = MIN_FREE_BYTES  # espacio libre extra sobre el triple del video
COPY_BUFFER = 1024 * 1024
UPLOAD_ID = re.compile(r"[0-9a-f]{32}")
NOT_FOUND = "Subida no encontrada."


class UploadNotFound(JobError):
    status_code = 404


class UploadTooLarge(JobError):
    status_code = 413


class ChunkOutOfRange(JobError):
    status_code = 409


class ChunkTooLarge(JobError):
    status_code = 413


class UploadIncomplete(JobError):
    status_code = 409


class UploadMismatch(JobError):
    status_code = 400


class UploadBusy(JobError):
    status_code = 409


def ensamblar(carpeta_trozos: Path, total: int, destino: Path) -> None:
    """Copia los trozos 0 a total-1, en orden, en destino. Va por bloques: nunca carga un trozo entero en memoria."""
    with destino.open("wb") as salida:
        for numero in range(total):
            with (carpeta_trozos / str(numero)).open("rb") as trozo:
                shutil.copyfileobj(trozo, salida, COPY_BUFFER)


def _escribir_json(ruta: Path, datos: dict[str, Any]) -> None:
    temporal = ruta.with_name(ruta.name + ".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    os.replace(temporal, ruta)


def _tocar(ruta: Path) -> None:
    os.utime(ruta, None)


def _ultima_actividad(carpeta: Path) -> float:
    """Última vez que cambió algo dentro de la subida: la fecha más reciente de la carpeta y de sus archivos."""
    fechas = [carpeta.stat().st_mtime]
    for ruta in carpeta.rglob("*"):
        try:
            fechas.append(ruta.stat().st_mtime)
        except FileNotFoundError:
            continue
    return max(fechas)


class UploadManager:
    """Subidas por partes. El estado está en disco (meta.json y los trozos): cualquier proceso sobre la misma carpeta de
    datos puede recibir un trozo o completar la subida."""

    def __init__(self, data_dir: Path, settings: Settings) -> None:
        self.root = data_dir / UPLOADS_DIR
        self.settings = settings
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # Ciclo de vida

    def start(self) -> None:
        """Limpia lo caducado al arrancar y después cada hora, en segundo plano."""
        self._limpiar_sin_fallar()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="subs-uploads", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.wait(CLEAN_EVERY_SECONDS):
            self._limpiar_sin_fallar()

    def _limpiar_sin_fallar(self) -> None:
        try:
            self.cleanup()
        except Exception:  # una limpieza fallida no debe parar las siguientes ni el arranque
            logger.exception("Falló la limpieza de subidas")

    # Alta y estado

    def create(self, filename: str, size: int, content_type: str, chunk_bytes: int | None = None) -> dict[str, Any]:
        ext = validate_upload(filename, content_type)  # 400: extensión o content-type que no corresponde
        if size > self.settings.max_upload_bytes:
            raise UploadTooLarge(f"El archivo es demasiado grande (límite: {self.settings.max_upload_bytes / MB:g} MB).")
        self.root.mkdir(parents=True, exist_ok=True)
        libre = jobs.espacio_libre(self.root)
        if libre < 3 * size + MARGIN_BYTES:  # el video, los trozos y el armado a la vez, más un margen
            raise NoDiskSpace(mensaje_sin_espacio(libre))
        upload_id = uuid.uuid4().hex
        carpeta = self.root / upload_id
        (carpeta / CHUNKS_DIR).mkdir(parents=True)
        chunk = chunk_bytes or self.settings.chunk_bytes  # desde el Mac, trozos más grandes (ver app.create_upload)
        total = math.ceil(size / chunk)
        _escribir_json(carpeta / META_FILE, {"ext": ext, "size": size, "chunk_size": chunk, "total_chunks": total})
        return {"upload_id": upload_id, "chunk_size": chunk, "total_chunks": total}

    def status(self, upload_id: str) -> dict[str, Any]:
        meta = self._meta(upload_id)
        trozos = self._dir(upload_id) / CHUNKS_DIR
        recibidos = sorted(int(ruta.name) for ruta in trozos.iterdir() if ruta.name.isdigit())
        return {"received": recibidos, "total_chunks": meta["total_chunks"], "size": meta["size"]}

    # Trozos

    def check_chunk(self, upload_id: str, n: int) -> int:
        """Comprueba la subida y el número de trozo. Devuelve el tamaño máximo de un trozo."""
        meta = self._meta(upload_id)
        if not 0 <= n < meta["total_chunks"]:
            ultimo = meta["total_chunks"] - 1
            raise ChunkOutOfRange(
                f"El trozo {n} no existe: el video tiene {meta['total_chunks']} trozos (del 0 al {ultimo})."
            )
        return meta["chunk_size"]

    def chunk_too_large(self, limite: int) -> ChunkTooLarge:
        return ChunkTooLarge(f"El trozo supera {limite / MB:g} MB (SUBS_CHUNK_MB).")

    def temp_chunk(self, upload_id: str, n: int) -> Path:
        """Ruta provisional del trozo: solo toma su nombre definitivo cuando llega entero."""
        return self._dir(upload_id) / CHUNKS_DIR / f"{n}.part"

    def commit_chunk(self, upload_id: str, n: int) -> None:
        """Pone el trozo en su sitio. Si ya estaba, lo sustituye: reenviar un trozo es seguro."""
        try:
            os.replace(self.temp_chunk(upload_id, n), self._dir(upload_id) / CHUNKS_DIR / str(n))
        except FileNotFoundError as exc:
            raise UploadNotFound(NOT_FOUND) from exc

    # Completar

    def begin_complete(self, upload_id: str) -> tuple[dict[str, Any], Path]:
        """Comprueba que están todos los trozos, con su tamaño, y aparta la subida para armarla. Devuelve sus datos y la
        carpeta apartada. Una segunda petición ya no la encuentra: se está completando."""
        meta = self._meta(upload_id)
        carpeta = self._dir(upload_id)
        total, chunk, size = meta["total_chunks"], meta["chunk_size"], meta["size"]
        trozos = carpeta / CHUNKS_DIR
        faltan = [n for n in range(total) if not (trozos / str(n)).is_file()]
        if faltan:
            lista = ", ".join(str(n) for n in faltan)
            raise UploadIncomplete(f"Faltan trozos: {lista}. Súbelos y vuelve a completar.")
        llegados = sum((trozos / str(n)).stat().st_size for n in range(total))
        if llegados != size:
            raise UploadMismatch(f"El tamaño no coincide: se declararon {size} bytes y llegaron {llegados}.")
        for n in range(total):
            esperado = min(chunk, size - n * chunk)
            real = (trozos / str(n)).stat().st_size
            if real != esperado:
                raise UploadMismatch(f"El trozo {n} mide {real} bytes y debía medir {esperado}.")
        apartada = carpeta.with_name(carpeta.name + ARMANDO)
        try:
            _tocar(carpeta)  # la actividad empieza ya: una cancelación que llegue durante el armado la ve reciente
            os.rename(carpeta, apartada)
        except FileNotFoundError as exc:
            raise UploadNotFound(NOT_FOUND) from exc
        except OSError as exc:
            raise UploadIncomplete("La subida no se puede completar ahora mismo.") from exc
        _tocar(apartada)  # la actividad empieza de nuevo: la limpieza no la toca mientras se arma
        return meta, apartada

    def assemble(self, apartada: Path, meta: dict[str, Any], destino: Path) -> None:
        ensamblar(apartada / CHUNKS_DIR, meta["total_chunks"], destino)

    def finish_complete(self, upload_id: str) -> None:
        """La subida ya es un job: se borran sus trozos."""
        shutil.rmtree(self.root / (upload_id + ARMANDO), ignore_errors=True)

    def abort_complete(self, upload_id: str) -> None:
        """Devuelve la subida a su sitio para que el cliente pueda volver a completarla."""
        try:
            os.rename(self.root / (upload_id + ARMANDO), self.root / upload_id)
        except OSError:
            logger.exception("No se pudo devolver la subida %s a su sitio", upload_id)

    # Cancelar

    def cancel(self, upload_id: str) -> None:
        """Borra la subida y sus trozos al momento. La aparta primero: desde ese instante ningún PUT ni GET la encuentra,
        aunque el borrado tarde. Si complete la está armando, responde 409 y no toca nada."""
        carpeta = self._dir(upload_id)  # 404 si el id no tiene formato válido
        apartada = self.root / (upload_id + BORRANDO)
        try:
            os.rename(carpeta, apartada)
        except FileNotFoundError as exc:
            self._cancelar_armado(upload_id, apartada, exc)
        try:
            shutil.rmtree(apartada)
        except OSError:
            logger.warning(
                "No se borraron del todo los trozos de la subida %s: la limpieza los quitará", upload_id, exc_info=True
            )

    def _cancelar_armado(self, upload_id: str, apartada: Path, causa: OSError) -> None:
        """La subida no está en su sitio. Si complete la está armando, 409. Si el armado se cortó y lleva un rato sin
        actividad, lo aparta para borrarlo. Si no hay nada, 404."""
        armando = self.root / (upload_id + ARMANDO)
        try:
            actividad = armando.stat().st_mtime
        except FileNotFoundError as exc:
            raise UploadNotFound(NOT_FOUND) from exc
        if time.time() - actividad < ARMANDO_EN_CURSO_SECONDS:
            raise UploadBusy("La subida se está completando: no se puede cancelar todavía.") from causa
        try:
            os.rename(armando, apartada)
        except FileNotFoundError as exc:
            raise UploadNotFound(NOT_FOUND) from exc

    # Limpieza

    def cleanup(self, now: float | None = None) -> int:
        """Borra las subidas sin actividad durante más de 24 h, y los restos de cancelaciones que no terminaron.
        Devuelve cuántas subidas borró."""
        if not self.root.is_dir():
            return 0
        ahora = time.time() if now is None else now
        borradas = 0
        for carpeta in list(self.root.iterdir()):
            if carpeta.name.endswith(BORRANDO):  # nadie la usa: es lo que quedó de una cancelación
                shutil.rmtree(carpeta, ignore_errors=True)
                continue
            try:
                caducada = carpeta.is_dir() and ahora - _ultima_actividad(carpeta) > MAX_AGE_SECONDS
            except OSError:
                continue  # desapareció mientras la miraba: alguien la está completando o borrando
            if caducada:
                shutil.rmtree(carpeta, ignore_errors=True)
                borradas += 1
        if borradas:
            logger.info("Subidas sin actividad borradas: %d", borradas)
        return borradas

    # Auxiliares

    def _dir(self, upload_id: str) -> Path:
        if not UPLOAD_ID.fullmatch(upload_id):
            raise UploadNotFound(NOT_FOUND)
        return self.root / upload_id

    def _meta(self, upload_id: str) -> dict[str, Any]:
        try:
            return json.loads((self._dir(upload_id) / META_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UploadNotFound(NOT_FOUND) from exc
