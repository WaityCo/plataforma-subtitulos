"""Dos procesos sobre la misma SUBS_DATA_DIR (B1): el dueño muere a mitad de transcripción y el otro toma el worker."""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from backend.jobs import LOCK_FILE, RESTART_ERROR

RAIZ = Path(__file__).resolve().parents[2]
SEGUNDOS_POR_TRANSCRIPCION = 15


def _puerto_libre() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _levantar(puerto, data_dir, carpeta_logs):
    entorno = {**os.environ, "SUBS_DATA_DIR": str(data_dir), "SUBS_PRUEBA_TRANSCRIPCION_S": str(SEGUNDOS_POR_TRANSCRIPCION)}
    registro = open(carpeta_logs / f"servidor-{puerto}.log", "w", encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, "-m", "backend.tests.servidor_prueba", str(puerto)],
        cwd=RAIZ,
        env=entorno,
        stdout=registro,
        stderr=subprocess.STDOUT,
    )


def _url(puerto, ruta):
    return f"http://127.0.0.1:{puerto}{ruta}"


def _esperar_api(puerto, timeout=60.0):
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        try:
            if httpx.get(_url(puerto, "/api/presets"), timeout=2.0).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise AssertionError(f"el servidor del puerto {puerto} no responde")


def _subir(puerto, video):
    with video.open("rb") as archivo:
        respuesta = httpx.post(_url(puerto, "/api/jobs"), files={"file": (video.name, archivo, "video/mp4")}, timeout=60)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["job_id"]


def _estado(puerto, job_id):
    return httpx.get(_url(puerto, f"/api/jobs/{job_id}"), timeout=5.0).json()


def _esperar_estado(puerto, job_id, estado, timeout):
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        job = _estado(puerto, job_id)
        if job["status"] == estado:
            return job
        time.sleep(0.25)
    raise AssertionError(f"el job {job_id} no llegó a '{estado}': {_estado(puerto, job_id)}")


def _dueño(data_dir) -> int:
    return json.loads((data_dir / LOCK_FILE).read_text(encoding="utf-8"))["pid"]


def test_el_otro_proceso_toma_el_worker_si_el_dueño_muere_a_mitad_de_transcripcion(tmp_path, sample_videos):
    data_dir = tmp_path / "data"
    puerto_dueño, puerto_otro = _puerto_libre(), _puerto_libre()
    dueño = _levantar(puerto_dueño, data_dir, tmp_path)
    otro = None
    try:
        _esperar_api(puerto_dueño)
        assert _dueño(data_dir) == dueño.pid  # el primero en arrancar toma el lock
        otro = _levantar(puerto_otro, data_dir, tmp_path)
        _esperar_api(puerto_otro)

        en_curso = _subir(puerto_dueño, sample_videos["sample.mp4"])
        en_cola = _subir(puerto_dueño, sample_videos["sample.mp4"])  # espera detrás del que transcribe
        _esperar_estado(puerto_dueño, en_curso, "transcribing", timeout=30)

        inicio = time.monotonic()
        dueño.send_signal(signal.SIGTERM)  # el dueño cierra a mitad de transcripción
        dueño.wait(timeout=60)
        nuevo = _subir(puerto_otro, sample_videos["sample.mp4"])  # el 2.º proceso recibe un job nuevo

        limite = inicio + 30
        while _estado(puerto_otro, en_curso)["status"] != "error":
            assert time.monotonic() < limite, "el 2.º proceso no tomó el worker en 30 s"
            time.sleep(0.25)
        assert _estado(puerto_otro, en_curso)["error"] == RESTART_ERROR
        assert _dueño(data_dir) == otro.pid

        _esperar_estado(puerto_otro, en_cola, "ready", timeout=90)
        _esperar_estado(puerto_otro, nuevo, "ready", timeout=90)
    finally:
        for proceso in (dueño, otro):
            if proceso is not None and proceso.poll() is None:
                proceso.kill()
                proceso.wait()
