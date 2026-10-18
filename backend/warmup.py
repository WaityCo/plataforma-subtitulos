"""Precalentamiento en segundo plano. El primer fotograma de cada preset tarda porque el motor carga las métricas de
su fuente, y el primer gancho carga Pillow y la fuente de emoji. Un hilo lo hace al arrancar: la API responde de
inmediato y, cuando termina, los primeros fotogramas ya no pagan esa carga."""

import logging
import string
import tempfile
import threading

logger = logging.getLogger(__name__)

# Todas las letras del español y los signos de los subtítulos: cada glifo cuesta la primera vez que aparece.
MUESTRA_TEXTO = "¿Quieres ganar dinero? ¡Hola! Ñandú árbol éxito úlcera íbamos ÁÉÍÓÚÜÑ 3.000 € 25% 0123456789 ,;:()-\"'"
MUESTRA_PALABRAS = [
    {"text": palabra, "start": i * 0.5, "end": i * 0.5 + 0.5}
    for i, palabra in enumerate(MUESTRA_TEXTO.split() + list(string.ascii_letters))
]
MUESTRA_GANCHO = {"headline": "Gancho", "kicker": "K", "news_title": "T", "news_subtitle": "S", "duration_s": 1}


def _warm_texts() -> None:
    """Construye un ASS de muestra con cada preset: así se cargan las métricas de todas sus fuentes."""
    from .engine_bridge import RealEngine

    motor = RealEngine()
    for preset in motor.list_presets():
        motor.build_ass(MUESTRA_PALABRAS, motor.resolve_style(preset["id"], None), 720, 1280)


def _draw_hook_sample() -> None:
    from engine.hook import render_hook

    with tempfile.TemporaryDirectory(prefix="warm-hook-") as carpeta:
        render_hook(MUESTRA_GANCHO, 1080, 1920, out_dir=carpeta)


def warm_up() -> None:
    """Carga lo que usa el primer fotograma. Si algo falla, la app sigue y solo queda el aviso."""
    try:
        _warm_texts()
        _draw_hook_sample()
    except Exception:
        logger.warning("No se pudo precalentar el render; el primer fotograma tardará más.", exc_info=True)


def start_warmup() -> threading.Thread:
    """Arranca el precalentamiento en un hilo en segundo plano, sin retrasar el arranque de la API."""
    thread = threading.Thread(target=warm_up, name="subs-warmup", daemon=True)
    thread.start()
    return thread
