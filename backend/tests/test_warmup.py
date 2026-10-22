"""Precalentamiento: corre en segundo plano, pasa por cada preset, deja cargado el gancho y no rompe la app si falla.
La carga del modelo de transcripción se prueba aquí; cuándo se pide, en test_precarga_dueno.py."""

import logging
import threading

from backend import warmup
from backend.engine_bridge import RealEngine
from engine import transcribe

# La de verdad. conftest.py la sustituye en el resto de tests, para no cargar Whisper en cada arranque de la API.
REAL_TRANSCRIPCION = warmup._warm_transcription


def test_el_precalentamiento_pasa_por_cada_preset(monkeypatch):
    llamadas = []
    principal = threading.main_thread()  # los hilos de arranques anteriores también precalientan: solo cuenta este

    def registrar(self, words, style, width, height):
        if threading.current_thread() is principal:
            llamadas.append(style)

    monkeypatch.setattr(RealEngine, "build_ass", registrar)

    warmup.warm_up()

    assert len(llamadas) == len(RealEngine().list_presets())


def test_el_precalentamiento_deja_cargado_el_gancho(caplog):
    with caplog.at_level(logging.WARNING):
        warmup.warm_up()

    from engine import hook  # la caché de la fuente de emoji es lo que ahorra la carga de la primera pastilla

    assert hook._emoji_font.cache_info().currsize == 1
    assert not [registro for registro in caplog.records if registro.levelno >= logging.WARNING]


def test_un_fallo_del_precalentamiento_solo_deja_un_aviso(monkeypatch, caplog):
    def roto():
        raise RuntimeError("sin fuentes")

    monkeypatch.setattr(warmup, "_warm_texts", roto)

    with caplog.at_level(logging.WARNING):
        warmup.warm_up()

    assert any("precalentar" in registro.getMessage() for registro in caplog.records)


def test_el_precalentamiento_corre_en_un_hilo_en_segundo_plano():
    hilo = warmup.start_warmup()
    hilo.join(timeout=60)

    assert hilo.daemon
    assert not hilo.is_alive()


def test_cargar_modelo_pide_al_motor_el_modelo_de_los_jobs(monkeypatch):
    cargados = []
    principal = threading.main_thread()  # los hilos de arranques anteriores también cargan el modelo: solo cuenta este
    monkeypatch.setattr(warmup, "_warm_transcription", REAL_TRANSCRIPCION)
    monkeypatch.setattr(
        transcribe,
        "warmup",
        lambda model_size=None: cargados.append(model_size) if threading.current_thread() is principal else None,
    )

    warmup.cargar_modelo("medium")

    assert cargados == ["medium"]


def test_un_fallo_al_cargar_el_modelo_solo_deja_un_aviso(monkeypatch, caplog):
    def roto(model_size=None):
        raise RuntimeError("sin modelo")

    monkeypatch.setattr(warmup, "_warm_transcription", REAL_TRANSCRIPCION)
    monkeypatch.setattr(transcribe, "warmup", roto)

    with caplog.at_level(logging.WARNING):
        warmup.cargar_modelo("tiny")

    assert any("modelo de transcripción" in registro.getMessage() for registro in caplog.records)
