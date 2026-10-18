"""GET /api/jobs/{id}/segments: el estilo guardado del job, o una vista previa con ?preset= y ?overrides=."""

import json
import uuid

import pytest

from backend.tests.helpers import upload, wait_for


def _job_listo(client, sample_videos):
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")
    return job_id


def test_segments_usan_el_estilo_guardado_del_job(start_app, sample_videos):
    client, engine = start_app()
    job_id = _job_listo(client, sample_videos)

    response = client.get(f"/api/jobs/{job_id}/segments")

    assert response.status_code == 200
    assert [segment["lines"][0][0]["text"] for segment in response.json()] == ["hola", "mundo"]
    assert engine.segment_calls[-1]["style"]["font_size"] == 86  # ken_classic, el defecto
    assert (engine.segment_calls[-1]["width"], engine.segment_calls[-1]["height"]) == (720, 1280)


def test_segments_usan_las_palabras_editadas(start_app, sample_videos):
    client, _ = start_app()
    job_id = _job_listo(client, sample_videos)
    client.put(f"/api/jobs/{job_id}/words", json=[{"text": "amigos", "start": 0, "end": 1.2}])

    segments = client.get(f"/api/jobs/{job_id}/segments").json()

    assert [segment["lines"][0][0]["text"] for segment in segments] == ["amigos"]


def test_segments_con_preset_y_overrides_no_guardan_nada(start_app, sample_videos):
    client, engine = start_app()
    job_id = _job_listo(client, sample_videos)
    preset_guardado = client.get(f"/api/jobs/{job_id}").json()["preset"]

    # La consulta va con la URL ya codificada, como la enviaría el frontend.
    response = client.get(f"/api/jobs/{job_id}/segments?preset=phrase_box&overrides=%7B%22font_size%22%3A70%7D")

    assert response.status_code == 200
    assert engine.segment_calls[-1]["style"]["font_size"] == 70
    assert engine.segment_calls[-1]["style"]["mode"] == "phrase"
    assert client.get(f"/api/jobs/{job_id}").json()["preset"] == preset_guardado
    assert "FontSize: 86" in client.get(f"/api/jobs/{job_id}/ass").text  # el ASS guardado no cambia


def test_segments_con_preset_inexistente_da_422(start_app, sample_videos):
    client, _ = start_app()
    job_id = _job_listo(client, sample_videos)

    response = client.get(f"/api/jobs/{job_id}/segments", params={"preset": "no_existe"})

    assert response.status_code == 422
    assert "no_existe" in response.json()["detail"]
    assert client.get(f"/api/jobs/{job_id}/segments", params={"preset": ""}).status_code == 422


@pytest.mark.parametrize("overrides", ["{no es json", "[1, 2]", json.dumps({"font_size": -3})])
def test_segments_con_overrides_invalidos_da_422(start_app, sample_videos, overrides):
    client, _ = start_app()
    job_id = _job_listo(client, sample_videos)

    response = client.get(f"/api/jobs/{job_id}/segments", params={"overrides": overrides})

    assert response.status_code == 422


def test_segments_sin_palabras_da_409_y_job_inexistente_404(start_app, sample_videos):
    client, engine = start_app()
    engine.gate.clear()  # la transcripción queda a medias: todavía no hay words.json
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "transcribing", percent=42.0)

    assert client.get(f"/api/jobs/{job_id}/segments").status_code == 409
    assert client.get(f"/api/jobs/{uuid.uuid4().hex}/segments").status_code == 404
