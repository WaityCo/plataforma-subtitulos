"""Limpieza de subidas por partes: caducan a las 24 h sin actividad; se limpian al arrancar y cada hora."""

import os
import time
from pathlib import Path

import pytest

from backend.config import Settings
from backend.uploads import ARMANDO, BORRANDO, MAX_AGE_SECONDS, UploadManager


@pytest.fixture(autouse=True)
def _disco_suficiente(monkeypatch):
    monkeypatch.setattr("backend.jobs.espacio_libre", lambda path: 10 * 1024 * 1024 * 1024)


def _gestor(data_dir: Path) -> UploadManager:
    return UploadManager(data_dir, Settings(data_dir=data_dir))


def _envejecer(carpeta: Path) -> None:
    """Deja la subida como si nadie la hubiera tocado en 25 h."""
    antes = time.time() - MAX_AGE_SECONDS - 3600
    for ruta in [carpeta, *carpeta.rglob("*")]:
        os.utime(ruta, (antes, antes))


def test_la_limpieza_borra_solo_lo_caducado(tmp_path):
    gestor = _gestor(tmp_path)
    viejo = gestor.create("a.mp4", 1000, "video/mp4")["upload_id"]
    nuevo = gestor.create("b.mp4", 1000, "video/mp4")["upload_id"]
    _envejecer(tmp_path / "uploads" / viejo)

    assert gestor.cleanup() == 1
    assert not (tmp_path / "uploads" / viejo).exists()
    assert (tmp_path / "uploads" / nuevo).exists()


def test_las_subidas_apartadas_para_armar_tambien_caducan(tmp_path):
    gestor = _gestor(tmp_path)
    uid = gestor.create("a.mp4", 1000, "video/mp4")["upload_id"]
    apartada = tmp_path / "uploads" / (uid + ARMANDO)
    os.rename(tmp_path / "uploads" / uid, apartada)  # como si un armado se hubiera cortado a mitad
    _envejecer(apartada)

    assert _gestor(tmp_path).cleanup() == 1
    assert not apartada.exists()


def test_sin_carpeta_de_subidas_la_limpieza_no_hace_nada(tmp_path):
    assert _gestor(tmp_path).cleanup() == 0


def test_al_arrancar_la_app_limpia_las_subidas_caducadas(start_app, tmp_path):
    uid = _gestor(tmp_path / "data").create("a.mp4", 1000, "video/mp4")["upload_id"]
    _envejecer(tmp_path / "data" / "uploads" / uid)

    start_app()

    assert not (tmp_path / "data" / "uploads" / uid).exists()


def test_la_limpieza_periodica_arranca_y_se_para(tmp_path):
    gestor = _gestor(tmp_path)
    gestor.start()
    hilo = gestor._thread
    assert hilo.is_alive()

    gestor.stop()

    assert not hilo.is_alive()


def test_la_limpieza_quita_los_restos_de_una_cancelacion_aunque_sean_recientes(tmp_path):
    resto = tmp_path / "uploads" / ("0" * 32 + BORRANDO)
    (resto / "chunks").mkdir(parents=True)
    (resto / "chunks" / "0").write_bytes(b"x" * 10)

    _gestor(tmp_path).cleanup()

    assert not resto.exists()
