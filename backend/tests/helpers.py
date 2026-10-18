"""Ayudas para las pruebas de la API."""

import time
from pathlib import Path


def upload(client, path: Path, *, filename: str | None = None, content_type: str = "video/mp4", **fields):
    """Sube un archivo como multipart a POST /api/jobs."""
    with path.open("rb") as handle:
        return client.post("/api/jobs", files={"file": (filename or path.name, handle, content_type)}, data=fields)


def wait_for(client, job_id: str, status: str, *, percent: float | None = None, timeout: float = 20.0) -> dict:
    """Consulta GET /api/jobs/{id} hasta llegar al estado (y al porcentaje, si se pide)."""
    deadline = time.monotonic() + timeout
    job: dict = {}
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] == "error":
            raise AssertionError(f"el job terminó en error: {job['error']}")
        if job["status"] == status and (percent is None or job["percent"] == percent):
            return job
        time.sleep(0.02)
    raise AssertionError(f"timeout esperando {status}; último estado: {job}")


def job_row(job_id: str, status: str) -> dict:
    """Fila de job como la guarda JobStore.create, para sembrar la base en las pruebas."""
    now = time.time()
    return {
        "id": job_id,
        "status": status,
        "stage": "transcribe",
        "percent": 42.0,
        "error": None,
        "input_ext": ".mp4",
        "width": 720,
        "height": 1280,
        "duration": 2.0,
        "preset": "ken_classic",
        "overrides": None,
        "language": None,
        "model_size": "small",
        "created_at": now,
        "updated_at": now,
    }
