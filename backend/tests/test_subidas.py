"""Subida por partes: flujo completo, reanudar, completar y los errores de cada paso."""

import errno
import math
import os
import time

import pytest

from backend import uploads
from backend.config import MB
from backend.tests.helpers import wait_for


def _partes(datos: bytes, tamano: int) -> list[bytes]:
    return [datos[i : i + tamano] for i in range(0, len(datos), tamano)]


def _para_tres(size: int) -> int:
    """Tamaño de trozo que reparte un archivo de `size` bytes en tres trozos."""
    return math.ceil(size / 3)


def _iniciar(client, size, nombre="sample.mp4", tipo="video/mp4"):
    return client.post("/api/uploads", json={"filename": nombre, "size": size, "content_type": tipo})


def _trozo(client, upload_id, n, datos):
    return client.put(f"/api/uploads/{upload_id}/chunks/{n}", content=datos)


def _completar(client, upload_id, **campos):
    return client.post(f"/api/uploads/{upload_id}/complete", json=campos)


def _sembrar(client, datos, tamano, nombre="sample.mp4"):
    """Inicia una subida de `datos` y devuelve su id y sus trozos ya partidos."""
    upload_id = _iniciar(client, len(datos), nombre=nombre).json()["upload_id"]
    return upload_id, _partes(datos, tamano)


def test_subida_en_tres_trozos_llega_a_ready(start_app, sample_videos):
    datos = sample_videos["sample.mp4"].read_bytes()
    client, _ = start_app(chunk_bytes=_para_tres(len(datos)))

    inicio = _iniciar(client, len(datos))
    assert inicio.status_code == 201
    subida = inicio.json()
    assert subida["total_chunks"] == 3
    assert subida["chunk_size"] == _para_tres(len(datos))
    upload_id = subida["upload_id"]

    for n, parte in enumerate(_partes(datos, subida["chunk_size"])):
        assert _trozo(client, upload_id, n, parte).json() == {"chunk": n, "bytes": len(parte)}
    estado = client.get(f"/api/uploads/{upload_id}").json()
    assert estado == {"received": [0, 1, 2], "total_chunks": 3, "size": len(datos)}

    completa = _completar(client, upload_id)
    assert completa.status_code == 201
    job = wait_for(client, completa.json()["job_id"], "ready")
    assert job["video"]["duration"] == 2.0
    assert client.get(f"/api/uploads/{upload_id}").status_code == 404  # los trozos se borraron


def test_reanudar_salta_los_trozos_recibidos_y_sobrescribe_los_repetidos(start_app, sample_videos):
    datos = sample_videos["sample.mp4"].read_bytes()
    tamano = _para_tres(len(datos))
    client, _ = start_app(chunk_bytes=tamano)
    upload_id, partes = _sembrar(client, datos, tamano)

    assert _trozo(client, upload_id, 0, partes[0]).status_code == 200
    assert _trozo(client, upload_id, 2, partes[2]).status_code == 200
    assert client.get(f"/api/uploads/{upload_id}").json()["received"] == [0, 2]

    # Reenviar un trozo lo sustituye: vale el último envío.
    assert _trozo(client, upload_id, 0, b"x" * len(partes[0])).status_code == 200
    assert _trozo(client, upload_id, 0, partes[0]).status_code == 200

    assert _trozo(client, upload_id, 1, partes[1]).status_code == 200
    completa = _completar(client, upload_id)
    assert completa.status_code == 201
    job = wait_for(client, completa.json()["job_id"], "ready")
    assert job["video"]["duration"] == 2.0


def test_completar_con_trozos_que_faltan_da_409_y_conserva_la_subida(start_app, sample_videos):
    datos = sample_videos["sample.mp4"].read_bytes()
    tamano = _para_tres(len(datos))
    client, _ = start_app(chunk_bytes=tamano)
    upload_id, partes = _sembrar(client, datos, tamano)
    _trozo(client, upload_id, 0, partes[0])

    respuesta = _completar(client, upload_id)

    assert respuesta.status_code == 409
    assert respuesta.json()["detail"] == "Faltan trozos: 1, 2. Súbelos y vuelve a completar."
    assert client.get(f"/api/uploads/{upload_id}").json()["received"] == [0]


def test_tamano_declarado_distinto_del_real_da_400(start_app, sample_videos):
    datos = sample_videos["sample.mp4"].read_bytes()
    declarado = len(datos) + 7
    tamano = _para_tres(declarado)
    client, _ = start_app(chunk_bytes=tamano)
    upload_id = _iniciar(client, declarado).json()["upload_id"]
    for n, parte in enumerate(_partes(datos, tamano)):
        assert _trozo(client, upload_id, n, parte).status_code == 200

    respuesta = _completar(client, upload_id)

    assert respuesta.status_code == 400
    assert respuesta.json()["detail"].startswith("El tamaño no coincide")


def test_contenido_que_no_es_video_da_400_y_borra_la_subida(start_app, tmp_path):
    datos = b"esto no es un video " * 4000
    tamano = _para_tres(len(datos))
    client, _ = start_app(chunk_bytes=tamano)
    upload_id, partes = _sembrar(client, datos, tamano, nombre="falso.mp4")
    for n, parte in enumerate(partes):
        _trozo(client, upload_id, n, parte)

    respuesta = _completar(client, upload_id)

    assert respuesta.status_code == 400
    assert "video" in respuesta.json()["detail"]
    assert client.get(f"/api/uploads/{upload_id}").status_code == 404
    assert list((tmp_path / "data" / "jobs").iterdir()) == []


@pytest.mark.parametrize("libre_mb, esperado", [(799, 507), (800, 201)])
def test_el_disco_necesario_es_el_triple_del_video_mas_500_mb(start_app, monkeypatch, libre_mb, esperado):
    client, _ = start_app()
    monkeypatch.setattr("backend.jobs.espacio_libre", lambda path: libre_mb * MB)

    respuesta = _iniciar(client, 100 * MB)

    assert respuesta.status_code == esperado
    if esperado == 507:
        assert respuesta.json() == {
            "detail": f"No hay espacio suficiente en disco (quedan {libre_mb} MB). Libera espacio y vuelve a intentarlo."
        }


def test_disco_que_se_llena_al_guardar_un_trozo_da_507(start_app, sample_videos, monkeypatch):
    datos = sample_videos["sample.mp4"].read_bytes()
    tamano = _para_tres(len(datos))
    client, _ = start_app(chunk_bytes=tamano)
    upload_id, partes = _sembrar(client, datos, tamano)

    def sin_espacio(self, upload_id, n):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(uploads.UploadManager, "commit_chunk", sin_espacio)
    respuesta = _trozo(client, upload_id, 0, partes[0])
    monkeypatch.undo()

    assert respuesta.status_code == 507
    assert respuesta.json()["detail"].startswith("No hay espacio suficiente en disco")
    assert client.get(f"/api/uploads/{upload_id}").json()["received"] == []


def test_disco_que_se_llena_al_completar_conserva_la_subida(start_app, sample_videos, monkeypatch, tmp_path):
    datos = sample_videos["sample.mp4"].read_bytes()
    tamano = _para_tres(len(datos))
    client, _ = start_app(chunk_bytes=tamano)
    upload_id, partes = _sembrar(client, datos, tamano)
    for n, parte in enumerate(partes):
        _trozo(client, upload_id, n, parte)

    def sin_espacio(carpeta_trozos, total, destino):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(uploads, "ensamblar", sin_espacio)
    respuesta = _completar(client, upload_id)
    monkeypatch.undo()

    assert respuesta.status_code == 507
    assert client.get(f"/api/uploads/{upload_id}").json()["received"] == [0, 1, 2]
    assert list((tmp_path / "data" / "jobs").iterdir()) == []

    completa = _completar(client, upload_id)  # la subida volvió a su sitio: se reintenta
    assert completa.status_code == 201
    wait_for(client, completa.json()["job_id"], "ready")


def test_trozo_mas_grande_que_el_tamano_da_413_tambien_sin_longitud_declarada(start_app, sample_videos):
    datos = sample_videos["sample.mp4"].read_bytes()
    tamano = _para_tres(len(datos))
    client, _ = start_app(chunk_bytes=tamano)
    upload_id, _ = _sembrar(client, datos, tamano)
    grande = b"x" * (tamano + 1)

    assert _trozo(client, upload_id, 0, grande).status_code == 413
    en_trozos = (grande[i : i + 4096] for i in range(0, len(grande), 4096))  # sin Content-Length
    assert client.put(f"/api/uploads/{upload_id}/chunks/0", content=en_trozos).status_code == 413
    assert client.get(f"/api/uploads/{upload_id}").json()["received"] == []


def test_numero_de_trozo_fuera_de_rango_da_409(start_app, sample_videos):
    datos = sample_videos["sample.mp4"].read_bytes()
    tamano = _para_tres(len(datos))
    client, _ = start_app(chunk_bytes=tamano)
    upload_id, _ = _sembrar(client, datos, tamano)

    for n in (3, -1):
        respuesta = _trozo(client, upload_id, n, b"x")
        assert respuesta.status_code == 409
        assert "no existe" in respuesta.json()["detail"]


def test_subida_mayor_que_el_limite_da_413(start_app):
    client, _ = start_app(max_upload_bytes=10_000)

    assert _iniciar(client, 10_001).status_code == 413
    assert _iniciar(client, 10_000).status_code == 201


def test_extension_no_admitida_da_400_y_tamano_no_valido_422(start_app):
    client, _ = start_app()

    assert _iniciar(client, 100, nombre="nota.txt").status_code == 400
    assert _iniciar(client, 0).status_code == 422


def test_subida_inexistente_da_404(start_app):
    client, _ = start_app()
    inexistente = "0" * 32

    assert client.get(f"/api/uploads/{inexistente}").status_code == 404
    assert _trozo(client, inexistente, 0, b"x").status_code == 404
    assert _completar(client, inexistente).status_code == 404
    assert client.get("/api/uploads/no-es-un-id").status_code == 404


def test_ajustes_no_validos_al_completar_dan_422_y_conservan_la_subida(start_app, sample_videos):
    datos = sample_videos["sample.mp4"].read_bytes()
    tamano = _para_tres(len(datos))
    client, _ = start_app(chunk_bytes=tamano)
    upload_id, partes = _sembrar(client, datos, tamano)
    for n, parte in enumerate(partes):
        _trozo(client, upload_id, n, parte)

    respuesta = _completar(client, upload_id, preset="no_existe")

    assert respuesta.status_code == 422
    assert client.get(f"/api/uploads/{upload_id}").json()["received"] == [0, 1, 2]


def test_cancelar_borra_la_subida_y_sus_trozos_al_momento(start_app, tmp_path):
    client, _ = start_app(chunk_bytes=10)
    upload_id, partes = _sembrar(client, b"x" * 30, 10)
    assert _trozo(client, upload_id, 0, partes[0]).status_code == 200
    carpeta = tmp_path / "data" / "uploads"
    assert (carpeta / upload_id / "chunks" / "0").is_file()

    cancelada = client.delete(f"/api/uploads/{upload_id}")

    assert cancelada.status_code == 204
    assert cancelada.content == b""
    assert list(carpeta.iterdir()) == []  # ni la carpeta ni restos
    assert client.get(f"/api/uploads/{upload_id}").status_code == 404
    assert _trozo(client, upload_id, 1, partes[1]).status_code == 404


def test_cancelar_dos_veces_la_segunda_da_404(start_app):
    client, _ = start_app(chunk_bytes=10)
    upload_id, _ = _sembrar(client, b"x" * 30, 10)

    assert client.delete(f"/api/uploads/{upload_id}").status_code == 204
    assert client.delete(f"/api/uploads/{upload_id}").status_code == 404


@pytest.mark.parametrize("upload_id", ["0" * 32, "no-es-un-id"])
def test_cancelar_una_subida_que_no_existe_da_404(start_app, upload_id):
    client, _ = start_app()

    assert client.delete(f"/api/uploads/{upload_id}").status_code == 404


def test_cancelar_mientras_se_completa_da_409_y_no_toca_nada(start_app, tmp_path):
    client, _ = start_app(chunk_bytes=10)
    upload_id, partes = _sembrar(client, b"x" * 30, 10)
    for n, parte in enumerate(partes):
        _trozo(client, upload_id, n, parte)
    gestor = client.app.state.uploads
    gestor.begin_complete(upload_id)  # una petición de completar está armando el video
    armando = tmp_path / "data" / "uploads" / (upload_id + uploads.ARMANDO)

    assert client.delete(f"/api/uploads/{upload_id}").status_code == 409
    assert armando.is_dir()

    gestor.abort_complete(upload_id)  # el armado falla y la subida vuelve a su sitio
    assert client.delete(f"/api/uploads/{upload_id}").status_code == 204


def test_cancelar_un_armado_cortado_hace_rato_lo_borra(start_app, tmp_path):
    client, _ = start_app(chunk_bytes=10)
    upload_id, partes = _sembrar(client, b"x" * 30, 10)
    for n, parte in enumerate(partes):
        _trozo(client, upload_id, n, parte)
    client.app.state.uploads.begin_complete(upload_id)  # el proceso se corta aquí, sin terminar el armado
    armando = tmp_path / "data" / "uploads" / (upload_id + uploads.ARMANDO)
    antes = time.time() - uploads.ARMANDO_EN_CURSO_SECONDS - 60
    os.utime(armando, (antes, antes))

    assert client.delete(f"/api/uploads/{upload_id}").status_code == 204
    assert list((tmp_path / "data" / "uploads").iterdir()) == []


def test_si_el_borrado_falla_la_subida_queda_oculta_y_la_limpieza_quita_el_resto(
    start_app, tmp_path, monkeypatch, caplog
):
    client, _ = start_app(chunk_bytes=10)
    upload_id, partes = _sembrar(client, b"x" * 30, 10)
    _trozo(client, upload_id, 0, partes[0])
    carpeta = tmp_path / "data" / "uploads"
    borrar = uploads.shutil.rmtree

    def disco_roto(ruta, *args, **kwargs):
        raise OSError(errno.EIO, "disco")

    monkeypatch.setattr(uploads.shutil, "rmtree", disco_roto)
    cancelada = client.delete(f"/api/uploads/{upload_id}")
    monkeypatch.setattr(uploads.shutil, "rmtree", borrar)

    assert cancelada.status_code == 204
    assert client.get(f"/api/uploads/{upload_id}").status_code == 404  # ya no la ve nadie
    assert (carpeta / (upload_id + uploads.BORRANDO)).is_dir()  # quedó el resto
    assert "No se borraron del todo" in caplog.text

    client.app.state.uploads.cleanup()  # la limpieza lo quita aunque sea reciente
    assert list(carpeta.iterdir()) == []
