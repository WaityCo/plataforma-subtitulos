"""Cabecera de Cloudflare Access: el correo se registra en el log del job y no autoriza nada."""

import logging

from backend.app import _solo_imprimible
from backend.tests.fakes import FakeEngine
from backend.tests.helpers import upload, wait_for

CABECERA = "Cf-Access-Authenticated-User-Email"
CORREO = "persona@example.com"


def _mensajes(caplog):
    return [registro.getMessage() for registro in caplog.records if registro.name == "backend.app"]


def test_la_subida_registra_el_correo_con_el_id_del_job(start_app, sample_videos, caplog):
    client, _ = start_app()

    with caplog.at_level(logging.INFO, logger="backend.app"):
        respuesta = client.post(
            "/api/jobs",
            files={"file": ("sample.mp4", sample_videos["sample.mp4"].read_bytes(), "video/mp4")},
            headers={CABECERA: CORREO},
        )

    job_id = respuesta.json()["job_id"]
    assert any(job_id in mensaje and CORREO in mensaje for mensaje in _mensajes(caplog))


def test_sin_la_cabecera_no_hay_registro_de_correo(start_app, sample_videos, caplog):
    client, _ = start_app()

    with caplog.at_level(logging.INFO, logger="backend.app"):
        upload(client, sample_videos["sample.mp4"])

    assert not any("Cloudflare Access" in mensaje for mensaje in _mensajes(caplog))


def test_las_ediciones_y_el_render_registran_el_correo(start_app, sample_videos, caplog):
    engine = FakeEngine()
    engine.burn_ok = True
    client, _ = start_app(engine=engine)
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")

    with caplog.at_level(logging.INFO, logger="backend.app"):
        client.put(
            f"/api/jobs/{job_id}/words", json=[{"text": "hola", "start": 0, "end": 1}], headers={CABECERA: CORREO}
        )
        client.put(f"/api/jobs/{job_id}/style", json={"preset": "phrase_box"}, headers={CABECERA: CORREO})
        client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": None}, headers={CABECERA: CORREO})

    mensajes = _mensajes(caplog)
    for accion in ("palabras", "estilo", "render"):
        assert any(accion in mensaje and job_id in mensaje for mensaje in mensajes), accion


def test_el_correo_se_limpia_antes_de_registrarlo():
    assert _solo_imprimible("a\nb\x00c@example.com") == "abc@example.com"
    assert len(_solo_imprimible("x" * 1000)) == 254


def test_la_cabecera_no_cambia_lo_que_responde_la_api(start_app, sample_videos):
    client, _ = start_app()
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")

    con = client.get(f"/api/jobs/{job_id}", headers={CABECERA: CORREO})
    sin = client.get(f"/api/jobs/{job_id}")

    assert con.json() == sin.json()
