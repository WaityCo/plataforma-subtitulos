"""Precarga del modelo solo en el proceso dueño del worker: al arrancar si tiene el lock, y tras un relevo."""

import json
import logging
import subprocess
import sys
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.jobs import LOCK_FILE, JobManager
from backend.tests.fakes import FakeEngine

INTERVALO = 0.1  # reintento y latido en décimas de segundo, para que las pruebas duren poco


@pytest.fixture
def otro_proceso():
    """Un proceso vivo que no es este: mientras viva, su lock es válido y este proceso no es el dueño."""
    proceso = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    yield proceso
    proceso.kill()
    proceso.wait()


def _lock_de(data_dir, pid):
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / LOCK_FILE).write_text(json.dumps({"pid": pid, "timestamp": time.time()}), encoding="utf-8")


def _esperar(condicion, timeout=5.0):
    limite = time.time() + timeout
    while time.time() < limite:
        if condicion():
            return True
        time.sleep(0.02)
    return False


def _gestor(data_dir, avisos):
    return JobManager(
        Settings(data_dir=data_dir),
        FakeEngine(),
        takeover_seconds=INTERVALO,
        heartbeat_seconds=INTERVALO,
        on_owner=lambda: avisos.append("dueño"),
    )


def test_el_dueno_avisa_al_arrancar(tmp_path):
    avisos = []
    gestor = _gestor(tmp_path, avisos)

    gestor.start()
    try:
        assert gestor.owner
        assert avisos == ["dueño"]
    finally:
        gestor.stop()


def test_quien_no_tiene_el_lock_no_avisa(tmp_path, otro_proceso):
    _lock_de(tmp_path, otro_proceso.pid)
    avisos = []
    gestor = _gestor(tmp_path, avisos)

    gestor.start()
    try:
        assert not gestor.owner
        assert avisos == []
    finally:
        gestor.stop()


def test_al_tomar_el_worker_tras_un_relevo_tambien_avisa(tmp_path, otro_proceso):
    _lock_de(tmp_path, otro_proceso.pid)
    avisos = []
    gestor = _gestor(tmp_path, avisos)
    gestor.start()
    try:
        assert avisos == []

        otro_proceso.kill()  # el dueño muere: su lock deja de ser válido y el reintento lo toma
        otro_proceso.wait()

        assert _esperar(lambda: gestor.owner)
        assert avisos == ["dueño"]
    finally:
        gestor.stop()


def test_un_fallo_al_avisar_no_para_el_worker(tmp_path, caplog):
    def roto():
        raise RuntimeError("sin modelo")

    gestor = JobManager(Settings(data_dir=tmp_path), FakeEngine(), on_owner=roto)

    with caplog.at_level(logging.WARNING):
        gestor.start()
    try:
        assert gestor.owner
        assert gestor._worker.is_alive()
        assert any("aviso de dueño" in registro.getMessage() for registro in caplog.records)
    finally:
        gestor.stop()


def test_la_app_que_tiene_el_lock_precarga_el_modelo_por_defecto(monkeypatch, tmp_path):
    pedidos = []
    monkeypatch.setattr("backend.app.precargar_modelo", lambda model_size=None: pedidos.append(model_size))
    settings = replace(Settings(data_dir=tmp_path / "datos"), default_model="tiny")
    app = create_app(
        settings=settings,
        engine=FakeEngine(),
        frontend_dir=tmp_path / "sin-frontend",
        presets_dir=tmp_path / "sin-presets",
    )

    with TestClient(app):
        pass

    assert pedidos == ["tiny"]


def test_la_app_sin_el_lock_no_precarga_el_modelo(monkeypatch, tmp_path, otro_proceso):
    pedidos = []
    monkeypatch.setattr("backend.app.precargar_modelo", lambda model_size=None: pedidos.append(model_size))
    _lock_de(tmp_path / "datos", otro_proceso.pid)
    app = create_app(
        settings=Settings(data_dir=tmp_path / "datos"),
        engine=FakeEngine(),
        frontend_dir=tmp_path / "sin-frontend",
        presets_dir=tmp_path / "sin-presets",
    )

    with TestClient(app) as client:
        assert client.get("/api/config").status_code == 200

    assert pedidos == []
