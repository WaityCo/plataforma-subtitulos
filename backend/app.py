"""API HTTP de la plataforma de subtítulos. Rutas y códigos de error según api.md."""

import errno
import json
import logging
import shutil
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, FastAPI, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from . import __version__, thumbs
from .acceso import ClaveDeAcceso
from .config import MB, MIN_PREVIEW_SECONDS, MODEL_SIZES, PROJECT_ROOT, Settings, resolve_default_preset
from .engine_bridge import FONTS_DIR, EngineUnavailable, RealEngine
from .jobs import ASS_FILE, OUTPUT_FILE, PREVIEW_FILE, JobError, JobManager, comprobar_espacio, error_de_espacio
from .media import UPLOAD_TYPES, InvalidVideo, probe_video, validate_upload
from .uploads import UploadManager, UploadNotFound
from .warmup import start_warmup

FRONTEND_DIR = PROJECT_ROOT / "frontend"
PRESETS_DIR = PROJECT_ROOT / "presets"
STOPWORDS_FILE = "stopwords.json"
FORM_OVERHEAD_BYTES = 64 * 1024  # margen para los campos del formulario y el multipart
LANGUAGES = {"es", "en"}
ACCESS_EMAIL_HEADER = "cf-access-authenticated-user-email"  # la pone Cloudflare Access: solo se registra

logger = logging.getLogger(__name__)


class StyleIn(BaseModel):
    preset: str = Field(min_length=1)
    overrides: dict[str, Any] | None = None


class WordIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=1)
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    emph: StrictBool | None = None  # true, false, o None si se omite (automático)

    @model_validator(mode="after")
    def _ordered(self) -> "WordIn":
        if self.end < self.start:
            raise ValueError("end no puede ser menor que start")
        return self


class HookIn(BaseModel):
    # Gancho titular de la apertura (engine/hook.py). Los campos desconocidos responden 422.
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(max_length=200)
    kicker: str | None = Field(default=None, max_length=200)
    news_title: str | None = Field(default=None, max_length=200)
    news_subtitle: str | None = Field(default=None, max_length=200)
    duration_s: float = Field(ge=0.5, le=10)

    @field_validator("headline")
    @classmethod
    def _headline_con_texto(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("no puede estar vacío")
        return value


class RenderIn(BaseModel):
    # El máximo lo fija SUBS_MAX_PREVIEW_SECONDS y se comprueba en JobManager.request_render.
    preview_seconds: float | None = Field(default=None, ge=MIN_PREVIEW_SECONDS)
    hook: HookIn | None = None  # sin hook, el render usa el gancho guardado del job


class _PayloadTooLarge(Exception):
    """El cuerpo superó el límite mientras llegaba por chunks."""


class _OptionalStaticFiles(StaticFiles):
    """StaticFiles para carpetas que pueden aparecer después del arranque, como frontend/.

    Starlette comprueba la carpeta en la primera petición y falla con RuntimeError si no existe.
    Aquí se omite esa comprobación: mientras la carpeta falte, la respuesta es 404.
    """

    async def check_config(self) -> None:
        return None


router = APIRouter(prefix="/api")


def _jobs(request: Request) -> JobManager:
    return request.app.state.jobs


def _too_large(max_bytes: int) -> HTTPException:
    return HTTPException(413, f"El archivo es demasiado grande (límite: {max_bytes / (1024 * 1024):g} MB).")


async def _read_form(request: Request, max_bytes: int) -> FormData:
    """Lee el multipart por chunks y corta en cuanto el cuerpo supera el límite, sin esperar al final."""
    limit = max_bytes + FORM_OVERHEAD_BYTES

    async def capped(stream: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        seen = 0
        async for chunk in stream:
            seen += len(chunk)
            if seen > limit:
                raise _PayloadTooLarge
            yield chunk

    try:
        async with aclosing(request.stream()) as stream:
            parser = MultiPartParser(request.headers, capped(stream), max_files=1, max_fields=20)
            return await parser.parse()
    except _PayloadTooLarge as exc:
        raise _too_large(max_bytes) from exc
    except MultiPartException as exc:
        raise HTTPException(400, f"Formulario multipart inválido: {exc}") from exc


def _copy_upload(upload: UploadFile, target: Path) -> None:
    upload.file.seek(0)
    with target.open("wb") as out:
        shutil.copyfileobj(upload.file, out, 1024 * 1024)


def _text_field(form: FormData, name: str) -> str:
    value = form.get(name)
    return value.strip() if isinstance(value, str) else ""


def _parse_overrides(raw: str) -> dict[str, Any]:
    """Overrides como JSON de objeto. Un texto que no lo sea responde 422."""
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "overrides debe ser JSON válido.") from exc
    if not isinstance(value, dict):
        raise HTTPException(422, "overrides debe ser un objeto JSON.")
    return value


def _validar_ajustes(
    preset: str,
    overrides: dict[str, Any] | None,
    language: str | None,
    model_size: str,
    jobs: JobManager,
    settings: Settings,
    default_preset: str,
) -> dict[str, Any]:
    """Ajustes del job. POST /api/jobs y POST /api/uploads/{id}/complete responden igual ante un valor no válido."""
    preset = preset or default_preset
    if language is not None and language not in LANGUAGES:
        raise HTTPException(422, "language debe ser 'es', 'en' o vacío.")
    model_size = model_size or settings.default_model
    if model_size not in MODEL_SIZES:
        raise HTTPException(422, f"model_size no admitido: {model_size}.")
    jobs.validate_style(preset, overrides)  # ValueError del motor -> 422
    return {"preset": preset, "overrides": overrides, "language": language, "model_size": model_size}


def _job_settings(form: FormData, jobs: JobManager, settings: Settings, default_preset: str) -> dict[str, Any]:
    raw_overrides = _text_field(form, "overrides")
    overrides = _parse_overrides(raw_overrides) if raw_overrides else None
    return _validar_ajustes(
        _text_field(form, "preset"),
        overrides,
        _text_field(form, "language") or None,
        _text_field(form, "model_size"),
        jobs,
        settings,
        default_preset,
    )


def _solo_imprimible(valor: str) -> str:
    """Sin caracteres de control y con 254 como máximo, para que el valor no rompa el log."""
    return "".join(caracter for caracter in valor if caracter.isprintable())[:254]


def _registrar_correo_access(request: Request, job_id: str, accion: str) -> None:
    """Cloudflare Access pone aquí el correo del usuario. Solo se registra en el log del job: fuera de Access
    cualquiera puede enviar la cabecera, así que nunca sirve para autorizar."""
    correo = request.headers.get(ACCESS_EMAIL_HEADER)
    if correo:
        logger.info("Job %s · %s · correo de Cloudflare Access: %s", job_id, accion, _solo_imprimible(correo))


@router.get("/config")
def get_config(request: Request) -> dict[str, Any]:
    # Lo que el frontend necesita para mostrar los límites reales, sin copiarlos a mano.
    settings: Settings = request.app.state.settings
    return {
        "max_upload_mb": settings.max_upload_bytes // MB,
        "max_upload_bytes": settings.max_upload_bytes,
        "chunk_bytes": settings.chunk_bytes,
        "default_preset": request.app.state.default_preset,
        "version": __version__,
    }


@router.get("/presets")
def list_presets(request: Request) -> list[dict[str, Any]]:
    return _jobs(request).list_presets()


@router.get("/fonts")
def list_fonts(request: Request) -> list[Any]:
    # Catálogo tal cual lo devuelve el motor (engine.textmetrics.font_catalog).
    return _jobs(request).list_fonts()


@router.get("/stopwords")
def get_stopwords(request: Request) -> FileResponse:
    # Se sirve tal cual está en disco. Mientras no exista, la respuesta es 404.
    path = request.app.state.presets_dir / STOPWORDS_FILE
    if not path.is_file():
        raise HTTPException(404, f"Todavía no existe presets/{STOPWORDS_FILE}.")
    return FileResponse(path, media_type="application/json")


@router.post("/jobs", status_code=201)
async def create_job(request: Request) -> dict[str, str]:
    jobs = _jobs(request)
    settings: Settings = request.app.state.settings
    max_bytes = settings.max_upload_bytes
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes + FORM_OVERHEAD_BYTES:
        raise _too_large(max_bytes)  # rechazo rápido, sin leer el cuerpo
    comprobar_espacio(jobs.data_dir, int(declared) if declared.isdigit() else 0)  # antes de recibir el video

    form = await _read_form(request, max_bytes)
    try:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise HTTPException(400, "Falta el archivo (campo 'file').")
        ext = validate_upload(upload.filename or "", upload.content_type or "")
        if (upload.size or 0) > max_bytes:
            raise _too_large(max_bytes)
        comprobar_espacio(jobs.data_dir, upload.size or 0)  # con el tamaño real del archivo
        job_settings = _job_settings(form, jobs, settings, request.app.state.default_preset)

        # El nombre en disco lo pone el servidor: el del usuario nunca se usa como ruta.
        job_id = uuid.uuid4().hex
        folder = jobs.job_dir(job_id)
        folder.mkdir(parents=True)
        try:
            source = folder / f"input{ext}"
            try:
                await run_in_threadpool(_copy_upload, upload, source)
            except OSError as exc:
                if exc.errno == errno.ENOSPC:
                    raise error_de_espacio(jobs.data_dir) from exc
                raise
            info = await run_in_threadpool(probe_video, source)
            jobs.create_job(job_id=job_id, input_ext=ext, info=info, **job_settings)
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        _registrar_correo_access(request, job_id, "subida")
        return {"job_id": job_id}
    finally:
        await form.close()


class UploadIn(BaseModel):
    # Subida por partes: el archivo se describe antes de mandar ningún trozo.
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    content_type: str | None = None


class CompleteIn(BaseModel):
    # Los mismos campos que el formulario de POST /api/jobs. Todos opcionales.
    preset: str | None = None
    overrides: dict[str, Any] | None = None
    language: str | None = None
    model_size: str | None = None


def _uploads(request: Request) -> UploadManager:
    return request.app.state.uploads


@router.post("/uploads", status_code=201)
def create_upload(body: UploadIn, request: Request) -> dict[str, Any]:
    # Antes de aceptar ningún trozo: extensión (400), tamaño (413) y disco (507).
    return _uploads(request).create(body.filename, body.size, body.content_type or "")


@router.get("/uploads/{upload_id}")
def get_upload(upload_id: str, request: Request) -> dict[str, Any]:
    # Para reanudar: qué trozos ya están y cuántos de qué tamaño faltan.
    return _uploads(request).status(upload_id)


@router.put("/uploads/{upload_id}/chunks/{n}")
async def put_chunk(upload_id: str, n: int, request: Request) -> dict[str, int]:
    # Cuerpo crudo del trozo. Llega a un .part y solo toma su nombre cuando entra entero: reenviarlo lo sustituye.
    uploads = _uploads(request)
    limite = uploads.check_chunk(upload_id, n)  # 404 o 409 antes de leer nada
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limite:
        raise uploads.chunk_too_large(limite)  # rechazo rápido, sin leer el cuerpo
    temporal = uploads.temp_chunk(upload_id, n)
    recibidos = 0
    try:
        with temporal.open("wb") as salida:
            async for trozo in request.stream():
                recibidos += len(trozo)
                if recibidos > limite:  # también cuando el cliente no declara la longitud
                    raise uploads.chunk_too_large(limite)
                await run_in_threadpool(salida.write, trozo)
        uploads.commit_chunk(upload_id, n)
    except OSError as exc:
        temporal.unlink(missing_ok=True)
        if exc.errno == errno.ENOSPC:
            raise error_de_espacio(uploads.root) from exc
        if exc.errno == errno.ENOENT:
            raise UploadNotFound("Subida no encontrada.") from exc
        raise
    except BaseException:
        temporal.unlink(missing_ok=True)
        raise
    return {"chunk": n, "bytes": recibidos}


@router.post("/uploads/{upload_id}/complete", status_code=201)
async def complete_upload(upload_id: str, request: Request, body: CompleteIn | None = None) -> dict[str, str]:
    jobs = _jobs(request)
    uploads = _uploads(request)
    settings: Settings = request.app.state.settings
    datos = body or CompleteIn()
    ajustes = _validar_ajustes(
        (datos.preset or "").strip(),
        datos.overrides,
        (datos.language or "").strip() or None,
        (datos.model_size or "").strip(),
        jobs,
        settings,
        request.app.state.default_preset,
    )
    meta, apartada = uploads.begin_complete(upload_id)  # comprueba los trozos y aparta la subida
    job_id = uuid.uuid4().hex
    folder = jobs.job_dir(job_id)
    try:
        folder.mkdir(parents=True)
        source = folder / f"input{meta['ext']}"
        try:
            await run_in_threadpool(uploads.assemble, apartada, meta, source)
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                raise error_de_espacio(jobs.data_dir) from exc
            raise
        info = await run_in_threadpool(probe_video, source)
        jobs.create_job(job_id=job_id, input_ext=meta["ext"], info=info, **ajustes)
    except InvalidVideo:  # el contenido no es un video: la subida no sirve y se borra
        shutil.rmtree(folder, ignore_errors=True)
        uploads.finish_complete(upload_id)
        raise
    except BaseException:  # otro fallo, p. ej. sin espacio: la subida vuelve a su sitio para reintentar
        shutil.rmtree(folder, ignore_errors=True)
        uploads.abort_complete(upload_id)
        raise
    uploads.finish_complete(upload_id)
    _registrar_correo_access(request, job_id, "subida por partes")
    return {"job_id": job_id}


@router.delete("/uploads/{upload_id}", status_code=204)
def delete_upload(upload_id: str, request: Request) -> None:
    # Cancelar: los trozos dejan de ocupar disco ya. 404 si no existe; 409 si complete la está armando.
    _uploads(request).cancel(upload_id)


@router.get("/jobs/{job_id}")
def job_status(job_id: str, request: Request) -> dict[str, Any]:
    return _jobs(request).get_status(job_id)


@router.get("/jobs/{job_id}/words")
def get_words(job_id: str, request: Request) -> list[dict[str, Any]]:
    return _jobs(request).read_words(job_id)


@router.put("/jobs/{job_id}/words")
def put_words(job_id: str, body: list[WordIn], request: Request) -> list[dict[str, Any]]:
    palabras = _jobs(request).update_words(job_id, [word.model_dump() for word in body])
    _registrar_correo_access(request, job_id, "palabras")
    return palabras


@router.put("/jobs/{job_id}/style")
def put_style(job_id: str, body: StyleIn, request: Request) -> dict[str, Any]:
    estilo = _jobs(request).update_style(job_id, body.preset, body.overrides)
    _registrar_correo_access(request, job_id, "estilo")
    return estilo


@router.get("/jobs/{job_id}/segments")
def get_segments(
    job_id: str,
    request: Request,
    preset: str | None = Query(default=None, min_length=1),
    overrides: str | None = Query(default=None, min_length=1),
) -> list[Any]:
    # Sin consulta: el estilo guardado del job. Con ?preset= o ?overrides=: vista previa, sin guardar nada.
    parsed = _parse_overrides(overrides) if overrides is not None else None
    return _jobs(request).segments(job_id, preset, parsed)


@router.get("/jobs/{job_id}/preview-frame")
def get_preview_frame(
    job_id: str,
    request: Request,
    preset: str | None = Query(default=None, min_length=1),
    overrides: str | None = Query(default=None, min_length=1),
    t: float | None = Query(default=None, ge=0),
    w: int = Query(default=thumbs.DEFAULT_WIDTH, ge=thumbs.MIN_WIDTH, le=thumbs.MAX_WIDTH),
) -> Response:
    # Fotograma exacto del video con los subtítulos del preset. Sin t, el instante lo elige el servidor.
    parsed = _parse_overrides(overrides) if overrides is not None else None
    frame = _jobs(request).preview_frame(job_id, preset, parsed, t, w)
    etag = f'"{frame.key}"'
    headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=3600",
        "X-Frame-Time": f"{frame.time:.3f}",
    }
    if frame.empty:
        headers["X-Empty"] = "1"  # sin palabras: el fotograma va sin subtítulos
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=frame.path.read_bytes(), media_type="image/jpeg", headers=headers)


@router.post("/jobs/{job_id}/render", status_code=202)
def render(job_id: str, request: Request, body: RenderIn | None = None) -> dict[str, str]:
    # Sin hook, el render usa el gancho guardado del job; con uno, lo reemplaza y lo guarda.
    hook = body.hook.model_dump() if body and body.hook else None
    _jobs(request).request_render(job_id, body.preview_seconds if body else None, hook)
    _registrar_correo_access(request, job_id, "render")
    return {"job_id": job_id, "status": "rendering"}


@router.put("/jobs/{job_id}/hook")
def put_hook(job_id: str, request: Request, body: HookIn | None = Body(default=None)) -> dict[str, Any] | None:
    # El cuerpo null quita el gancho guardado. FastAPI trata un null como ausente, así que la falta de
    # cuerpo se comprueba aquí. Se valida igual que en POST /render.
    if request.headers.get("content-length", "0") == "0" and "transfer-encoding" not in request.headers:
        raise HTTPException(422, "Falta el cuerpo: un objeto con el gancho, o null para quitarlo.")
    hook = body.model_dump() if body else None
    guardado = _jobs(request).update_hook(job_id, hook)
    _registrar_correo_access(request, job_id, "gancho")
    return guardado


@router.get("/jobs/{job_id}/input")
def get_input(job_id: str, request: Request) -> FileResponse:
    path = _jobs(request).input_path(job_id)
    return FileResponse(path, media_type=UPLOAD_TYPES[path.suffix])


@router.get("/jobs/{job_id}/ass")
def get_ass(job_id: str, request: Request) -> FileResponse:
    return FileResponse(_jobs(request).artifact(job_id, ASS_FILE), media_type="text/plain; charset=utf-8")


@router.get("/jobs/{job_id}/output")
def get_output(job_id: str, request: Request) -> FileResponse:
    return FileResponse(_jobs(request).artifact(job_id, OUTPUT_FILE), media_type="video/mp4")


@router.get("/jobs/{job_id}/preview")
def get_preview(job_id: str, request: Request) -> FileResponse:
    return FileResponse(_jobs(request).artifact(job_id, PREVIEW_FILE), media_type="video/mp4")


async def _job_error(_: Request, exc: JobError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)


async def _engine_unavailable(_: Request, exc: EngineUnavailable) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=503)


async def _invalid_video(_: Request, exc: InvalidVideo) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=400)


async def _invalid_frame(_: Request, exc: thumbs.InvalidFrame) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=422)


async def _frame_error(_: Request, exc: thumbs.FrameError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=500)


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # El contrato devuelve {"detail": "texto"}, no la lista por defecto de FastAPI.
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    message = first.get("msg", "dato inválido")
    return JSONResponse({"detail": f"{where}: {message}" if where else message}, status_code=422)


def _configurar_log() -> None:
    """Los mensajes del backend, INFO incluido, salen por stderr. Sin esto, el log de los jobs no se vería."""
    registro = logging.getLogger("backend")
    if not registro.handlers:
        manejador = logging.StreamHandler()
        manejador.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        registro.addHandler(manejador)
    registro.setLevel(logging.INFO)


def create_app(
    *,
    settings: Settings | None = None,
    engine: Any = None,
    frontend_dir: Path | None = None,
    presets_dir: Path | None = None,
) -> FastAPI:
    """Crea la app. Sin settings, la configuración sale de las variables SUBS_* del entorno."""
    _configurar_log()
    settings = Settings.from_env() if settings is None else settings
    manager = JobManager(settings, RealEngine() if engine is None else engine)
    uploads = UploadManager(settings.data_dir, settings)
    # Se resuelve al crear la app: si SUBS_DEFAULT_PRESET no existe entre los presets, el arranque se detiene.
    default_preset = resolve_default_preset(settings.default_preset, [p["id"] for p in manager.list_presets()])

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        manager.start()
        uploads.start()  # limpia las subidas caducadas y sigue cada hora
        start_warmup()  # el motor de texto y el gancho se precalientan en segundo plano, sin retrasar el arranque
        try:
            yield
        finally:
            uploads.stop()
            manager.stop()

    # Con clave, la API va detrás de un proxy: no se publican documentación ni la interfaz (la sirve un Worker).
    ocultar = bool(settings.api_key)
    app = FastAPI(
        title="Plataforma de subtítulos",
        lifespan=lifespan,
        docs_url=None if ocultar else "/docs",
        redoc_url=None if ocultar else "/redoc",
        openapi_url=None if ocultar else "/openapi.json",
    )
    app.state.jobs = manager
    app.state.uploads = uploads
    app.state.settings = settings
    app.state.default_preset = default_preset
    app.state.presets_dir = presets_dir or PRESETS_DIR
    app.include_router(router)
    if settings.api_key:
        # Antes que CORS: CORS queda por fuera y responde los preflight sin pedir la clave.
        app.add_middleware(ClaveDeAcceso, clave=settings.api_key)
    if settings.cors_origins:
        # Con orígenes, el frontend puede estar en otro dominio (p. ej. Cloudflare Pages). Sin ellos, solo mismo origen.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=True,  # las cookies de Cloudflare Access viajan con la petición
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Content-Type", "If-None-Match", "Range"],
            expose_headers=["X-Frame-Time", "X-Empty", "ETag"],
        )
    app.add_exception_handler(JobError, _job_error)
    app.add_exception_handler(EngineUnavailable, _engine_unavailable)
    app.add_exception_handler(InvalidVideo, _invalid_video)
    app.add_exception_handler(thumbs.InvalidFrame, _invalid_frame)
    app.add_exception_handler(thumbs.FrameError, _frame_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    # Montajes siempre presentes: frontend/ puede crearse después del arranque. Las rutas /api van antes.
    app.mount("/fonts", _OptionalStaticFiles(directory=FONTS_DIR, check_dir=False), name="fonts")
    if not ocultar:
        app.mount(
            "/",
            _OptionalStaticFiles(directory=frontend_dir or FRONTEND_DIR, html=True, check_dir=False),
            name="frontend",
        )
    return app


app = create_app()
