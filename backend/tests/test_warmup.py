"""Precalentamiento: corre en segundo plano, pasa por cada preset, deja cargado el gancho y no rompe la app si falla."""

import logging

from backend import warmup
from backend.engine_bridge import RealEngine


def test_el_precalentamiento_pasa_por_cada_preset(monkeypatch):
    llamadas = []
    monkeypatch.setattr(RealEngine, "build_ass", lambda self, words, style, width, height: llamadas.append(style))

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
