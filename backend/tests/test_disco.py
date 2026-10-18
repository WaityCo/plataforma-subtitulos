"""Espacio en disco (B3): 507 antes de subir o renderizar, y el ENOSPC de FFmpeg llega al job como error de espacio."""

import errno
import os
import sqlite3
import time

import pytest

from backend.config import MB
from backend.jobs import JobStore, NoDiskSpace, comprobar_espacio, es_falta_de_espacio, mensaje_sin_espacio
from backend.tests.fakes import FakeEngine
from backend.tests.helpers import upload, wait_for


def _sin_espacio(mb):
    return f"No hay espacio suficiente en disco (quedan {mb} MB). Libera espacio y vuelve a intentarlo."


def _espacio(monkeypatch, mb):
    monkeypatch.setattr("backend.jobs.espacio_libre", lambda path: mb * MB)


def _espacio_por_pasos(monkeypatch, *mb):
    """Devuelve estos valores en orden y, luego, el último: el disco se llena entre dos comprobaciones."""
    restantes = [valor * MB for valor in mb]
    monkeypatch.setattr(
        "backend.jobs.espacio_libre", lambda path: restantes.pop(0) if len(restantes) > 1 else restantes[0]
    )


def _esperar_error(client, job_id, timeout=20.0):
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] == "error":
            return job
        time.sleep(0.02)
    raise AssertionError(f"el job no llegó a error: {job}")


class QuemadoSinEspacio(FakeEngine):
    def burn(self, **kwargs):
        raise RuntimeError("FFmpeg falló al quemar los subtítulos:\nNo space left on device")


class QuemadoConProgresoRoto(FakeEngine):
    def burn(self, *, progress=None, **kwargs):
        progress("burn", 50.0)  # la escritura del progreso falla con el disco lleno
        raise RuntimeError("FFmpeg falló al quemar los subtítulos:\nNo space left on device")


class QuemadoConOtroError(FakeEngine):
    def burn(self, **kwargs):
        raise RuntimeError("FFmpeg falló al quemar los subtítulos:\nOption not found")


def _copia_sin_espacio(upload, target):
    raise OSError(errno.ENOSPC, "No space left on device")


@pytest.mark.parametrize(
    "free_mb, input_mb, debe_fallar",
    [(499, 0, True), (500, 0, False), (700, 250, True), (800, 250, False), (899, 300, True), (900, 300, False)],
)
def test_comprobar_espacio_exige_500_mb_o_el_triple_del_video(monkeypatch, tmp_path, free_mb, input_mb, debe_fallar):
    _espacio(monkeypatch, free_mb)

    if debe_fallar:
        with pytest.raises(NoDiskSpace) as error:
            comprobar_espacio(tmp_path, input_mb * MB)
        assert str(error.value) == _sin_espacio(free_mb)
    else:
        comprobar_espacio(tmp_path, input_mb * MB)


def test_el_mensaje_redondea_los_mb_hacia_abajo():
    assert mensaje_sin_espacio(600 * MB + 900_000) == _sin_espacio(600)


@pytest.mark.parametrize(
    "exc, esperado",
    [
        (OSError(errno.ENOSPC, "No space left on device"), True),
        (RuntimeError("FFmpeg falló al quemar los subtítulos:\nNo space left on device"), True),
        (RuntimeError("FFmpeg falló: otro motivo"), False),
        (sqlite3.OperationalError("disk I/O error"), False),  # SQLite no basta: el progreso ya no lo propaga
    ],
)
def test_es_falta_de_espacio_reconoce_enospc_y_el_texto_de_ffmpeg(exc, esperado):
    assert es_falta_de_espacio(exc) is esperado


def test_subida_sin_espacio_da_507_y_no_deja_restos(start_app, sample_videos, tmp_path, monkeypatch):
    client, _ = start_app()
    _espacio(monkeypatch, 100)

    response = upload(client, sample_videos["sample.mp4"])

    assert response.status_code == 507
    assert response.json() == {"detail": _sin_espacio(100)}
    assert list((tmp_path / "data" / "jobs").iterdir()) == []


def test_copia_con_disco_lleno_da_507_y_no_deja_restos(start_app, sample_videos, tmp_path, monkeypatch):
    client, _ = start_app()
    _espacio_por_pasos(monkeypatch, 2000, 2000, 42)  # hay sitio al empezar, pero se agota al copiar
    monkeypatch.setattr("backend.app._copy_upload", _copia_sin_espacio)

    response = upload(client, sample_videos["sample.mp4"])

    assert response.status_code == 507
    assert response.json() == {"detail": _sin_espacio(42)}
    assert list((tmp_path / "data" / "jobs").iterdir()) == []


def test_render_sin_espacio_da_507_y_el_job_sigue_listo(start_app, sample_videos, monkeypatch):
    engine = FakeEngine()
    engine.burn_ok = True
    client, _ = start_app(engine=engine)
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")
    _espacio(monkeypatch, 200)

    response = client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": None})

    assert response.status_code == 507
    assert response.json() == {"detail": _sin_espacio(200)}
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "ready"


def test_render_cuenta_el_triple_del_video(start_app, sample_videos, monkeypatch):
    engine = FakeEngine()
    engine.burn_ok = True
    client, _ = start_app(engine=engine)
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")
    os.truncate(client.app.state.jobs.job_dir(job_id) / "input.mp4", 250 * MB)  # disperso: no ocupa disco real

    _espacio(monkeypatch, 600)  # 3 × 250 MB = 750 MB
    assert client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": None}).status_code == 507

    _espacio(monkeypatch, 800)
    assert client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": None}).status_code == 202
    wait_for(client, job_id, "done")


def test_ffmpeg_sin_espacio_deja_el_job_en_error_con_el_mensaje_de_espacio(start_app, sample_videos, monkeypatch):
    engine = QuemadoSinEspacio()
    engine.burn_ok = True
    client, _ = start_app(engine=engine)
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")
    _espacio_por_pasos(monkeypatch, 2000, 120)  # hay sitio al pedir el render; al fallar, quedan 120 MB

    assert client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": None}).status_code == 202
    job = _esperar_error(client, job_id)

    assert job["error"] == _sin_espacio(120)


def test_progreso_que_no_se_guarda_no_tapa_el_error_de_espacio(start_app, sample_videos, monkeypatch):
    original = JobStore.update

    def update(self, job_id, **fields):
        if fields.get("percent") == 50.0:  # solo el progreso del quemado: con el disco lleno, SQLite no escribe
            raise sqlite3.OperationalError("disk I/O error")
        return original(self, job_id, **fields)

    monkeypatch.setattr(JobStore, "update", update)
    engine = QuemadoConProgresoRoto()
    engine.burn_ok = True
    client, _ = start_app(engine=engine)
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")
    _espacio_por_pasos(monkeypatch, 2000, 120)

    assert client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": None}).status_code == 202
    job = _esperar_error(client, job_id)

    assert job["error"] == _sin_espacio(120)  # no «disk I/O error»


def test_error_que_no_es_de_espacio_conserva_su_mensaje(start_app, sample_videos):
    engine = QuemadoConOtroError()
    engine.burn_ok = True
    client, _ = start_app(engine=engine)
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")

    assert client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": None}).status_code == 202
    job = _esperar_error(client, job_id)

    assert job["error"] == "FFmpeg falló al quemar los subtítulos:\nOption not found"
