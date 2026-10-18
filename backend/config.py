"""Configuración de despliegue. Es el único módulo que lee variables SUBS_* del entorno.

SUBS_DATA_DIR (data/): carpeta de jobs, base SQLite y subs.lock. Una ruta relativa cuelga de la raíz.
SUBS_MAX_UPLOAD_MB (200): tamaño máximo de subida, en MB. Entero mayor que 0.
SUBS_DEFAULT_MODEL (small): modelo de Whisper si el formulario no pide otro.
SUBS_MAX_PREVIEW_SECONDS (15): duración máxima del preview, en segundos. El mínimo es 1.
SUBS_DEFAULT_PRESET (ken_remedie si el motor lo tiene; si no, ken_classic): preset si el formulario no pide otro.
SUBS_CORS_ORIGINS (vacío): orígenes que pueden llamar a la API desde otro dominio, separados por comas. Vacío: solo mismo origen.
SUBS_API_KEY (vacío): si se define, /api/* y /fonts/* exigen la cabecera X-Subs-Key con ese valor.
Una variable vacía equivale a no definirla. Un valor no válido detiene el arranque.
"""

import math
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_MAX_UPLOAD_MB = 200
DEFAULT_MODEL = "small"
DEFAULT_MAX_PREVIEW_SECONDS = 15
MIN_PREVIEW_SECONDS = 1
PREFERRED_PRESET = "ken_remedie"
FALLBACK_PRESET = "ken_classic"
MODEL_SIZES = frozenset({"tiny", "base", "small", "medium", "large-v2", "large-v3"})
MB = 1024 * 1024


class ConfigError(ValueError):
    """Una variable SUBS_* tiene un valor no válido. El arranque se detiene."""


@dataclass(frozen=True)
class Settings:
    """Valores de despliegue ya validados. Las pruebas los construyen directamente."""

    data_dir: Path = DEFAULT_DATA_DIR
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_MB * MB
    default_model: str = DEFAULT_MODEL
    max_preview_seconds: float = DEFAULT_MAX_PREVIEW_SECONDS
    default_preset: str | None = None  # None: se resuelve con resolve_default_preset
    cors_origins: tuple[str, ...] = ()  # vacío: solo mismo origen
    api_key: str | None = None  # None: la API no pide clave

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if environ is None else environ
        return cls(
            data_dir=_data_dir(env.get("SUBS_DATA_DIR")),
            max_upload_bytes=_upload_mb(env.get("SUBS_MAX_UPLOAD_MB")) * MB,
            default_model=_model(env.get("SUBS_DEFAULT_MODEL")),
            max_preview_seconds=_preview_seconds(env.get("SUBS_MAX_PREVIEW_SECONDS")),
            default_preset=_value(env.get("SUBS_DEFAULT_PRESET")),
            cors_origins=_cors_origins(env.get("SUBS_CORS_ORIGINS")),
            api_key=_value(env.get("SUBS_API_KEY")),
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


def _model(raw: str | None) -> str:
    value = _value(raw)
    if value is None:
        return DEFAULT_MODEL
    if value not in MODEL_SIZES:
        options = ", ".join(sorted(MODEL_SIZES))
        raise ConfigError(f"SUBS_DEFAULT_MODEL no admitido: {value!r}. Usa uno de: {options}.")
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


def _cors_origins(raw: str | None) -> tuple[str, ...]:
    """Orígenes de CORS separados por comas. Cada uno es esquema y host, sin ruta; una barra final se quita."""
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
                f"SUBS_CORS_ORIGINS no admite {item.strip()!r}: usa esquema y host, por ejemplo https://app.example.com."
            )
        origins.append(origin)
    return tuple(origins)
