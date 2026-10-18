"""Pruebas de la cola: migración de la BD y recuperación de jobs interrumpidos (solo para el dueño)."""

import sqlite3
import uuid

from backend.config import Settings
from backend.jobs import RESTART_ERROR, JobManager, JobStore
from backend.tests.fakes import FakeEngine
from backend.tests.helpers import job_row


def test_al_arrancar_lo_interrumpido_pasa_a_error(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    store.init()
    transcribing, rendering = uuid.uuid4().hex, uuid.uuid4().hex
    store.create(job_row(transcribing, "transcribing"))
    store.create(job_row(rendering, "rendering"))

    manager = JobManager(Settings(data_dir=tmp_path), FakeEngine())
    manager.start()
    manager.stop()

    for job_id in (transcribing, rendering):
        status = manager.get_status(job_id)
        assert status["status"] == "error"
        assert status["error"] == RESTART_ERROR
    assert manager.store.pop_next() is None  # ya no quedan pasos pendientes para ellos


def test_init_migra_una_cola_anterior_sin_preview(tmp_path):
    db = tmp_path / "jobs.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE queue (seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, kind TEXT NOT NULL)")
    conn.commit()
    conn.close()
    store = JobStore(db)

    store.init()
    store.enqueue(uuid.uuid4().hex, "render", 3.0)

    assert store.pop_next()["preview_seconds"] == 3.0
