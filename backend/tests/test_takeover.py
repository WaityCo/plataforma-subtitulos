"""Toma del worker (B1): un proceso sin lock reintenta tomarlo, y el dueño que pierde el lock deja de procesar."""

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from backend.config import Settings
from backend.jobs import LOCK_FILE, RESTART_ERROR, TAKEOVER_SECONDS, JobManager
from backend.tests.fakes import FakeEngine
from backend.tests.helpers import job_row

INTERVALO = 0.1  # reintento y latido en décimas de segundo, para que las pruebas duren poco
RAIZ = Path(__file__).resolve().parents[2]

# Cada proceso espera la señal de arranque, intenta tomar el lock y mantiene vivo su resultado hasta la señal de fin:
# si el ganador muriera, su lock caducaría y otro proceso podría tomarlo.
_CONTENDIENTE = """
import os, pathlib, sys, time
from backend.jobs import DataDirLock
data_dir, salida, arranque, fin = (pathlib.Path(argumento) for argumento in sys.argv[1:5])
while not arranque.exists():
    time.sleep(0.001)
resultado = DataDirLock(data_dir).acquire()
temporal = salida.with_suffix(".tmp")
temporal.write_text(str(resultado), encoding="utf-8")
os.replace(temporal, salida)
while not fin.exists():
    time.sleep(0.01)
"""


@pytest.fixture
def otro_proceso():
    proceso = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    yield proceso
    proceso.kill()
    proceso.wait()


def _pid_muerto() -> int:
    proceso = subprocess.Popen([sys.executable, "-c", "pass"])
    proceso.wait()
    return proceso.pid


def _escribir_lock(data_dir, pid):
    (data_dir / LOCK_FILE).write_text(json.dumps({"pid": pid, "timestamp": time.time()}), encoding="utf-8")


def _leer_pid(data_dir):
    return json.loads((data_dir / LOCK_FILE).read_text(encoding="utf-8"))["pid"]


def _manager(tmp_path):
    return JobManager(
        Settings(data_dir=tmp_path), FakeEngine(), takeover_seconds=INTERVALO, heartbeat_seconds=INTERVALO
    )


def _esperar(condicion, timeout=5.0):
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.02)
    return False


def _sembrar(manager, sample_video, status):
    job = uuid.uuid4().hex
    manager.store.create(job_row(job, status))
    manager.job_dir(job).mkdir(parents=True, exist_ok=True)
    shutil.copy(sample_video, manager.job_dir(job) / "input.mp4")  # el worker sondea el video al transcribir
    return job


def test_el_reintento_por_defecto_es_cada_15_s(tmp_path):
    assert TAKEOVER_SECONDS == 15.0
    assert JobManager(Settings(data_dir=tmp_path), FakeEngine()).takeover_seconds == 15.0


def test_el_proceso_sin_lock_toma_el_worker_cuando_el_dueño_muere(tmp_path, otro_proceso, sample_videos):
    manager = _manager(tmp_path)
    manager.store.init()
    en_curso = _sembrar(manager, sample_videos["sample.mp4"], "transcribing")
    en_cola = _sembrar(manager, sample_videos["sample.mp4"], "queued")
    _escribir_lock(tmp_path, otro_proceso.pid)
    manager.start()
    try:
        assert manager.owner is False

        otro_proceso.kill()  # el dueño muere: su pid deja de existir
        otro_proceso.wait()

        assert _esperar(lambda: manager.owner)
        assert manager.get_status(en_curso)["error"] == RESTART_ERROR
        assert _esperar(lambda: manager.get_status(en_cola)["status"] == "ready")
        assert _leer_pid(tmp_path) == os.getpid()
    finally:
        manager.stop()


def test_el_dueño_que_pierde_el_lock_deja_de_procesar_y_lo_retoma_despues(tmp_path, otro_proceso):
    manager = _manager(tmp_path)
    manager.start()
    try:
        assert manager.owner is True

        _escribir_lock(tmp_path, otro_proceso.pid)  # otro proceso toma el lock con una marca fresca
        assert _esperar(lambda: manager.owner is False)

        otro_proceso.kill()  # ese proceso muere: su lock caduca por pid
        otro_proceso.wait()
        assert _esperar(lambda: manager.owner is True)
    finally:
        manager.stop()


def test_stop_cierra_el_standby_y_el_worker(tmp_path):
    manager = _manager(tmp_path)
    manager.start()

    manager.stop()

    assert not manager._standby.is_alive()
    assert not manager._worker.is_alive()


def test_solo_un_proceso_toma_un_lock_caducado(tmp_path):
    for ronda in range(3):
        _escribir_lock(tmp_path, _pid_muerto())
        arranque, fin = tmp_path / f"arranque-{ronda}", tmp_path / f"fin-{ronda}"
        salidas = [tmp_path / f"salida-{ronda}-{numero}" for numero in range(6)]
        procesos = [
            subprocess.Popen(
                [sys.executable, "-c", _CONTENDIENTE, str(tmp_path), str(salida), str(arranque), str(fin)], cwd=RAIZ
            )
            for salida in salidas
        ]
        arranque.write_text("ya", encoding="utf-8")
        try:
            assert _esperar(lambda: all(salida.exists() for salida in salidas), timeout=60)
            resultados = [salida.read_text(encoding="utf-8") for salida in salidas]
            assert resultados.count("True") == 1, resultados
        finally:
            fin.write_text("ya", encoding="utf-8")
            for proceso in procesos:
                proceso.wait(timeout=30)
