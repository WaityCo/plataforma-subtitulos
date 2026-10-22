"""Configuración de despliegue. Es el único módulo que lee variables SUBS_* del entorno.

SUBS_DATA_DIR (data/): carpeta de jobs, base SQLite y subs.lock. Una ruta relativa cuelga de la raíz.
SUBS_MAX_UPLOAD_MB (1024): tamaño máximo de subida, en MB. Entero mayor que 0.
SUBS_CHUNK_MB (8): tamaño de cada trozo de la subida por partes, en MB. Entero de 1 a 90. Desde el Mac, 64 MB.
SUBS_UPLOAD_CONCURRENCY (3): trozos que se envían a la vez desde fuera del Mac. Entero de 1 a 8. Desde el Mac, uno.
SUBS_ASR_MODEL (small): modelo de Whisper de los jobs y de la API por defecto. Gana sobre SUBS_DEFAULT_MODEL.
SUBS_DEFAULT_MODEL (small): alias de SUBS_ASR_MODEL, solo si esta no está definida.
SUBS_ASR_ENGINE (faster-whisper): faster-whisper o mlx. Con mlx, mlx_whisper tiene que importarse al arrancar.
SUBS_VIDEO_ENCODER (auto): auto, videotoolbox o libx264.
SUBS_MAX_PREVIEW_SECONDS (15): duración máxima del preview, en segundos. El mínimo es 1.
SUBS_DEFAULT_PRESET (ken_remedie si el motor lo tiene; si no, ken_classic): preset si el formulario no pide otro.
SUBS_CORS_ORIGINS (vacío): orígenes que pueden llamar a la API desde otro dominio, separados por comas. Vacío: solo mismo origen.
SUBS_PUBLIC_ORIGINS (vacío): sitio público que puede consultar /api/local-ping para ofrecer la versión local. Mismo formato.
SUBS_API_KEY (vacío): si se define, /api/* y /fonts/* exigen la cabecera X-Subs-Key con ese valor, salvo desde el Mac.
Una variable vacía equivale a no definirla. Un valor no válido detiene el arranque.
"""

import importlib
import logging
import math
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_MAX_UPLOAD_MB = 1024
DEFAULT_CHUNK_MB = 8  # 8 MB tardan unos 28 s a 0,29 MB/s, por debajo de los 100 s de Cloudflare
MAX_CHUNK_MB = 90  # Tope de configuración: a 0,29 MB/s, un trozo de más de unos 29 MB ya supera los 100 s
DEFAULT_UPLOAD_CONCURRENCY = 3  # trozos en paralelo desde fuera del Mac
MAX_UPLOAD_CONCURRENCY = 8
DEFAULT_MODEL = "small"
DEFAULT_MAX_PREVIEW_SECONDS = 15
MIN_PREVIEW_SECONDS = 1
PREFERRED_PRESET = "ken_remedie"
FALLBACK_PRESET = "ken_classic"
ASR_ENGINES = ("faster-whisper", "mlx")  # las mismas que ENGINES en engine/transcribe.py
DEFAULT_ASR_ENGINE = "faster-whisper"
ASR_MODELS = ("tiny", "base", "small", "medium", "large-v2", "large-v3", "large-v3-turbo")  # las de MLX_MODELS
MODEL_SIZES = frozenset(ASR_MODELS)
VIDEO_ENCODERS = ("auto", "videotoolbox", "libx264")  # las mismas que VIDEO_ENCODERS en engine/burn.py
DEFAULT_VIDEO_ENCODER = "auto"
MB = 1024 * 1024
LOCAL_CHUNK_BYTES = 64 * MB  # desde el Mac no pasa por Cloudflare: trozos grandes y menos peticiones


class ConfigError(ValueError):
    """Una variable SUBS_* tiene un valor no válido. El arranque se detiene."""


@dataclass(frozen=True)
class Settings:
    """Valores de despliegue ya validados. Las pruebas los construyen directamente."""

    data_dir: Path = DEFAULT_DATA_DIR
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_MB * MB
    default_model: str = DEFAULT_MODEL  # modelo de los jobs y de la API: SUBS_ASR_MODEL, o SUBS_DEFAULT_MODEL
    max_preview_seconds: float = DEFAULT_MAX_PREVIEW_SECONDS
    default_preset: str | None = None  # None: se resuelve con resolve_default_preset
    cors_origins: tuple[str, ...] = ()  # vacío: solo mismo origen
    api_key: str | None = None  # None: la API no pide clave
    chunk_bytes: int = DEFAULT_CHUNK_MB * MB  # tamaño de cada trozo de la subida por partes
    upload_concurrency: int = DEFAULT_UPLOAD_CONCURRENCY  # trozos a la vez desde fuera del Mac
    public_origins: tuple[str, ...] = ()  # sitio público que puede consultar /api/local-ping
    asr_engine: str = DEFAULT_ASR_ENGINE  # SUBS_ASR_ENGINE
    video_encoder: str = DEFAULT_VIDEO_ENCODER  # SUBS_VIDEO_ENCODER

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if environ is None else environ
        return cls(
            data_dir=_data_dir(env.get("SUBS_DATA_DIR")),
            max_upload_bytes=_upload_mb(env.get("SUBS_MAX_UPLOAD_MB")) * MB,
            default_model=_modelo_por_defecto(env),
            max_preview_seconds=_preview_seconds(env.get("SUBS_MAX_PREVIEW_SECONDS")),
            default_preset=_value(env.get("SUBS_DEFAULT_PRESET")),
            cors_origins=_origenes(env.get("SUBS_CORS_ORIGINS"), "SUBS_CORS_ORIGINS"),
            api_key=_value(env.get("SUBS_API_KEY")),
            chunk_bytes=_chunk_mb(env.get("SUBS_CHUNK_MB")) * MB,
            upload_concurrency=_concurrency(env.get("SUBS_UPLOAD_CONCURRENCY")),
            public_origins=_origenes(env.get("SUBS_PUBLIC_ORIGINS"), "SUBS_PUBLIC_ORIGINS"),
            asr_engine=_opcion(env.get("SUBS_ASR_ENGINE"), "SUBS_ASR_ENGINE", ASR_ENGINES) or DEFAULT_ASR_ENGINE,
            video_encoder=_opcion(env.get("SUBS_VIDEO_ENCODER"), "SUBS_VIDEO_ENCODER", VIDEO_ENCODERS)
            or DEFAULT_VIDEO_ENCODER,
        )


def resolve_default_preset(explicit: str | None, available: Iterable[str]) -> str:
    """Preset por defecto de la API. Sin SUBS_DEFAULT_PRESET: ken_remedie si el motor lo tiene, si no ken_classic.

    Con la variable, el preset debe existir entre los del motor. Si no, el arranque se detiene.
    """
    ids = sorted(set(available))
    if explicit is None:
        return PREFERRED_PRESET if PREFERRED_PRESET in ids else FALLBACK_PRESET
    if explicit not in ids:
        options = ", ".join(ids)
        raise ConfigError(f"SUBS_DEFAULT_PRESET no existe entre los presets del motor: {explicit!r}. Disponibles: {options}.")
    return explicit


def comprobar_motor_asr(settings: Settings) -> None:
    """Con SUBS_ASR_ENGINE=mlx, mlx_whisper debe importarse. Si no, el arranque se detiene nombrando la variable."""
    if settings.asr_engine != "mlx":
        return
    try:
        _importar_mlx()
    except Exception as exc:  # ImportError, o un fallo al cargar la librería de Metal
        raise ConfigError(
            f"SUBS_ASR_ENGINE=mlx necesita mlx_whisper, y no se puede importar: {exc}. "
            "Instálalo en el venv (pip install mlx-whisper) o usa SUBS_ASR_ENGINE=faster-whisper."
        ) from exc


def _importar_mlx() -> None:
    importlib.import_module("mlx_whisper")  # aparte para que las pruebas la sustituyan


def _value(raw: str | None) -> str | None:
    """Valor sin espacios. None si la variable no está definida o está vacía."""
    if raw is None:
        return None
    cleaned = raw.strip()
    return cleaned or None


def _data_dir(raw: str | None) -> Path:
    value = _value(raw)
    if value is None:
        return DEFAULT_DATA_DIR
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _upload_mb(raw: str | None) -> int:
    value = _value(raw)
    if value is None:
        return DEFAULT_MAX_UPLOAD_MB
    try:
        megabytes = int(value)
    except ValueError as exc:
        raise ConfigError(f"SUBS_MAX_UPLOAD_MB debe ser un entero: {value!r}.") from exc
    if megabytes <= 0:
        raise ConfigError("SUBS_MAX_UPLOAD_MB debe ser mayor que 0.")
    return megabytes


def _chunk_mb(raw: str | None) -> int:
    value = _value(raw)
    if value is None:
        return DEFAULT_CHUNK_MB
    try:
        megabytes = int(value)
    except ValueError as exc:
        raise ConfigError(f"SUBS_CHUNK_MB debe ser un entero: {value!r}.") from exc
    if not 1 <= megabytes <= MAX_CHUNK_MB:
        raise ConfigError(f"SUBS_CHUNK_MB debe estar entre 1 y {MAX_CHUNK_MB}: {value!r}.")
    return megabytes


def _concurrency(raw: str | None) -> int:
    value = _value(raw)
    if value is None:
        return DEFAULT_UPLOAD_CONCURRENCY
    try:
        number = int(value)
    except ValueError as exc:
        raise ConfigError(f"SUBS_UPLOAD_CONCURRENCY debe ser un entero: {value!r}.") from exc
    if not 1 <= number <= MAX_UPLOAD_CONCURRENCY:
        raise ConfigError(f"SUBS_UPLOAD_CONCURRENCY debe estar entre 1 y {MAX_UPLOAD_CONCURRENCY}: {value!r}.")
    return number


def _modelo_por_defecto(env: Mapping[str, str]) -> str:
    """Modelo de los jobs y de la API. SUBS_ASR_MODEL gana; SUBS_DEFAULT_MODEL queda como alias de ella."""
    asr = _opcion(env.get("SUBS_ASR_MODEL"), "SUBS_ASR_MODEL", ASR_MODELS)
    alias = _opcion(env.get("SUBS_DEFAULT_MODEL"), "SUBS_DEFAULT_MODEL", ASR_MODELS)
    if asr and alias and asr != alias:
        logger.warning(
            "SUBS_ASR_MODEL=%s y SUBS_DEFAULT_MODEL=%s no coinciden: se usa %s. SUBS_DEFAULT_MODEL es un alias.",
            asr,
            alias,
            asr,
        )
    return asr or alias or DEFAULT_MODEL


def _opcion(raw: str | None, variable: str, options: tuple[str, ...]) -> str | None:
    """Valor de una lista cerrada, o None si no está definida. Fuera de la lista, el arranque se detiene."""
    value = _value(raw)
    if value is None:
        return None
    if value not in options:
        raise ConfigError(f"{variable} no admitido: {value!r}. Usa uno de: {', '.join(options)}.")
    return value


def _preview_seconds(raw: str | None) -> float:
    value = _value(raw)
    if value is None:
        return DEFAULT_MAX_PREVIEW_SECONDS
    try:
        seconds = float(value)
    except ValueError as exc:
        raise ConfigError(f"SUBS_MAX_PREVIEW_SECONDS debe ser un número: {value!r}.") from exc
    if not math.isfinite(seconds) or seconds < MIN_PREVIEW_SECONDS:
        raise ConfigError(f"SUBS_MAX_PREVIEW_SECONDS debe ser un número de al menos {MIN_PREVIEW_SECONDS}: {value!r}.")
    return seconds


def _origenes(raw: str | None, variable: str) -> tuple[str, ...]:
    """Orígenes separados por comas. Cada uno es esquema y host, sin ruta; una barra final se quita."""
    value = _value(raw)
    if value is None:
        return ()
    origins = []
    for item in value.split(","):
        origin = item.strip().rstrip("/")
        if not origin:
            continue
        parts = urlsplit(origin)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.path or parts.query or parts.fragment:
            raise ConfigError(
                f"{variable} no admite {item.strip()!r}: usa esquema y host, por ejemplo https://app.example.com."
            )
        origins.append(origin)
    return tuple(origins)
