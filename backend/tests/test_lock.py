"""Lock de la carpeta de datos (F4): solo el dueño de un lock válido recupera jobs."""

import json
import os
import subprocess
import sys
import time
import uuid

import pytest

from backend.config import Settings
from backend.jobs import LOCK_FILE, RESTART_ERROR, DataDirLock, JobManager, JobStore
from backend.tests.fakes import FakeEngine
from backend.tests.helpers import job_row


def _pid_muerto() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


@pytest.fixture
def otro_proceso():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    yield proc
    proc.kill()
    proc.wait()


def _escribir_lock(data_dir, pid, timestamp=None):
    content = {"pid": pid, "timestamp": time.time() if timestamp is None else timestamp}
    (data_dir / LOCK_FILE).write_text(json.dumps(content), encoding="utf-8")


def _leer_lock(data_dir):
    return json.loads((data_dir / LOCK_FILE).read_text(encoding="utf-8"))


def test_lock_de_un_proceso_muerto_se_recupera(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    store.init()
    job = uuid.uuid4().hex
    store.create(job_row(job, "transcribing"))
    _escribir_lock(tmp_path, _pid_muerto())

    manager = JobManager(Settings(data_dir=tmp_path), FakeEngine())
    manager.start()
    try:
        assert manager.owner is True
        assert manager.get_status(job)["error"] == RESTART_ERROR
        assert _leer_lock(tmp_path)["pid"] == os.getpid()
    finally:
        manager.stop()


def test_lock_vivo_de_otro_proceso_no_toca_los_jobs(tmp_path, otro_proceso):
    store = JobStore(tmp_path / "jobs.db")
    store.init()
    en_curso, en_cola = uuid.uuid4().hex, uuid.uuid4().hex
    store.create(job_row(en_curso, "transcribing"))
    store.create(job_row(en_cola, "queued"))
    _escribir_lock(tmp_path, otro_proceso.pid)

    manager = JobManager(Settings(data_dir=tmp_path), FakeEngine())
    manager.start()
    try:
        assert manager.owner is False
        assert manager.get_status(en_curso)["status"] == "transcribing"
        assert manager.get_status(en_cola)["status"] == "queued"  # sin worker: lo procesará el dueño
        assert _leer_lock(tmp_path)["pid"] == otro_proceso.pid
    finally:
        manager.stop()
    assert _leer_lock(tmp_path)["pid"] == otro_proceso.pid  # no se borra el lock ajeno


def test_lock_con_marca_caducada_se_recupera_aunque_el_pid_viva(tmp_path, otro_proceso):
    store = JobStore(tmp_path / "jobs.db")
    store.init()
    job = uuid.uuid4().hex
    store.create(job_row(job, "transcribing"))
    _escribir_lock(tmp_path, otro_proceso.pid, timestamp=time.time() - 10_000)

    manager = JobManager(Settings(data_dir=tmp_path), FakeEngine())
    manager.start()
    try:
        assert manager.owner is True
        assert manager.get_status(job)["error"] == RESTART_ERROR
    finally:
        manager.stop()


def test_stop_libera_el_lock(tmp_path):
    manager = JobManager(Settings(data_dir=tmp_path), FakeEngine())
    manager.start()
    assert (tmp_path / LOCK_FILE).is_file()
    manager.stop()
    assert not (tmp_path / LOCK_FILE).exists()


def test_lock_corrupto_se_trata_como_huerfano(tmp_path):
    (tmp_path / LOCK_FILE).write_text("no es json", encoding="utf-8")
    lock = DataDirLock(tmp_path)

    assert lock.acquire() is True
    lock.release()


def test_refresh_renueva_la_marca_de_tiempo(tmp_path):
    lock = DataDirLock(tmp_path)
    assert lock.acquire() is True
    primera = lock.read()["timestamp"]
    time.sleep(0.01)

    lock.refresh()

    assert lock.read()["timestamp"] > primera
    lock.release()
