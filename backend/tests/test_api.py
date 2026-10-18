"""Pruebas de la API según api.md: subida, estado, estilo, palabras, render, preview y archivos."""

import json
import uuid

import pytest

from backend.tests.fakes import FakeEngine
from backend.tests.helpers import upload, wait_for


def test_presets_vienen_del_motor(start_app):
    client, _ = start_app()

    response = client.get("/api/presets")

    assert response.status_code == 200
    assert [preset["id"] for preset in response.json()] == ["ken_classic", "phrase_box"]


@pytest.mark.parametrize(
    "name, content_type",
    [("sample.mp4", "video/mp4"), ("sample.mov", "video/quicktime"), ("sample.webm", "video/webm")],
)
def test_formatos_admitidos_llegan_a_ready(start_app, sample_videos, name, content_type):
    client, _ = start_app()

    response = upload(client, sample_videos[name], content_type=content_type)

    assert response.status_code == 201
    wait_for(client, response.json()["job_id"], "ready")


def test_subida_valida_expone_metadatos_y_archivos(start_app, sample_videos):
    client, engine = start_app()

    response = upload(client, sample_videos["sample.mp4"], preset="ken_classic")
    assert response.status_code == 201
    job_id = response.json()["job_id"]

    job = wait_for(client, job_id, "ready")
    assert job["video"] == {"width": 720, "height": 1280, "duration": 2.0}
    assert job["preset"] == "ken_classic"
    assert job["urls"] == {
        "input": f"/api/jobs/{job_id}/input",
        "words": f"/api/jobs/{job_id}/words",
        "ass": f"/api/jobs/{job_id}/ass",
        "output": None,
        "preview": None,
    }
    assert [word["text"] for word in client.get(f"/api/jobs/{job_id}/words").json()] == ["hola", "mundo"]
    assert "FontSize: 86" in client.get(f"/api/jobs/{job_id}/ass").text
    assert engine.transcriptions == 1


def test_progreso_del_motor_se_guarda_y_bloquea_ediciones(start_app, sample_videos):
    client, engine = start_app()
    engine.gate.clear()  # la transcripción se queda a medias
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]

    job = wait_for(client, job_id, "transcribing", percent=42.0)
    assert job["stage"] == "transcribe"
    assert client.put(f"/api/jobs/{job_id}/words", json=[{"text": "x", "start": 0, "end": 1}]).status_code == 409
    assert client.put(f"/api/jobs/{job_id}/style", json={"preset": "ken_classic"}).status_code == 409

    engine.gate.set()
    wait_for(client, job_id, "ready")


@pytest.mark.parametrize("name, content_type", [("nota.txt", "text/plain"), ("clip.mp4", "video/webm")])
def test_extension_o_content_type_invalidos_dan_400(start_app, name, content_type):
    client, _ = start_app()

    response = client.post("/api/jobs", files={"file": (name, b"x" * 100, content_type)})

    assert response.status_code == 400


def test_contenido_que_no_es_video_da_400_y_no_deja_restos(start_app, tmp_path):
    client, _ = start_app()

    response = client.post("/api/jobs", files={"file": ("falso.mp4", b"esto no es un video", "video/mp4")})

    assert response.status_code == 400
    assert "video" in response.json()["detail"]
    assert list((tmp_path / "data" / "jobs").iterdir()) == []


# 12 KB supera el límite y falla al validar el tamaño; 300 KB corta mientras el cuerpo llega por chunks.
@pytest.mark.parametrize("size", [12_000, 300_000])
def test_archivo_sobre_el_limite_da_413(start_app, tmp_path, size):
    client, _ = start_app(max_upload_bytes=10_000)

    response = client.post("/api/jobs", files={"file": ("grande.mp4", b"\0" * size, "video/mp4")})

    assert response.status_code == 413
    assert list((tmp_path / "data" / "jobs").iterdir()) == []


def test_estilo_valido_regenera_ass_sin_transcribir(start_app, sample_videos):
    client, engine = start_app()
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")

    response = client.put(f"/api/jobs/{job_id}/style", json={"preset": "phrase_box", "overrides": {"font_size": 70}})

    assert response.status_code == 200
    assert response.json()["font_size"] == 70
    assert "FontSize: 70" in client.get(f"/api/jobs/{job_id}/ass").text
    assert engine.transcriptions == 1


def test_estilo_invalido_da_422(start_app, sample_videos):
    client, _ = start_app()
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")

    unknown_preset = client.put(f"/api/jobs/{job_id}/style", json={"preset": "no_existe"})
    bad_value = client.put(
        f"/api/jobs/{job_id}/style", json={"preset": "ken_classic", "overrides": {"font_size": -3}}
    )

    assert unknown_preset.status_code == 422
    assert "no_existe" in unknown_preset.json()["detail"]
    assert bad_value.status_code == 422


def test_put_words_guarda_emph_y_regenera_ass(start_app, sample_videos, tmp_path):
    client, engine = start_app()
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")
    edited = [
        {"text": "Hola", "start": 0.0, "end": 0.5, "emph": True},
        {"text": "amigos", "start": 0.5, "end": 1.2, "emph": False},
        {"text": "hoy", "start": 1.2, "end": 1.5},  # sin emph: automático
    ]

    response = client.put(f"/api/jobs/{job_id}/words", json=edited)

    assert response.status_code == 200
    expected = [
        {"text": "Hola", "start": 0.0, "end": 0.5, "emph": True},
        {"text": "amigos", "start": 0.5, "end": 1.2, "emph": False},
        {"text": "hoy", "start": 1.2, "end": 1.5, "emph": None},
    ]
    assert client.get(f"/api/jobs/{job_id}/words").json() == expected
    saved = json.loads((tmp_path / "data" / "jobs" / job_id / "words.json").read_text(encoding="utf-8"))
    assert saved == expected
    assert "Dialogue: amigos" in client.get(f"/api/jobs/{job_id}/ass").text
    assert engine.transcriptions == 1


@pytest.mark.parametrize("emph", ["si", 1])
def test_put_words_rechaza_emph_que_no_es_booleano(start_app, sample_videos, emph):
    client, _ = start_app()
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")

    response = client.put(f"/api/jobs/{job_id}/words", json=[{"text": "x", "start": 0, "end": 1, "emph": emph}])

    assert response.status_code == 422


def test_put_words_rechaza_tiempos_invertidos(start_app, sample_videos):
    client, _ = start_app()
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")

    response = client.put(f"/api/jobs/{job_id}/words", json=[{"text": "x", "start": 2.0, "end": 1.0}])

    assert response.status_code == 422


def test_render_responde_501_sin_libass(start_app, sample_videos):
    client, _ = start_app()  # el motor falso arranca sin libass
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")

    response = client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": None})

    assert response.status_code == 501
    assert "libass" in response.json()["detail"]


def test_render_encola_y_termina_en_done(start_app, sample_videos):
    engine = FakeEngine()
    engine.burn_ok = True
    client, _ = start_app(engine=engine)
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")

    response = client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": None})

    assert response.status_code == 202
    job = wait_for(client, job_id, "done")
    assert job["urls"]["output"] == f"/api/jobs/{job_id}/output"
    output = client.get(f"/api/jobs/{job_id}/output")
    assert output.content == b"fake-mp4"
    assert output.headers["content-type"] == "video/mp4"


def test_progreso_del_quemado_se_guarda(start_app, sample_videos):
    engine = FakeEngine()
    engine.burn_ok = True
    engine.burn_gate.clear()  # el quemado se queda a medias
    client, _ = start_app(engine=engine)
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")
    assert client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": None}).status_code == 202

    job = wait_for(client, job_id, "rendering", percent=50.0)
    assert job["stage"] == "burn"

    engine.burn_gate.set()
    wait_for(client, job_id, "done")


def test_preview_de_3_s_se_guarda_aparte(start_app, sample_videos):
    engine = FakeEngine()
    engine.burn_ok = True
    client, _ = start_app(engine=engine)
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")

    response = client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": 3})

    assert response.status_code == 202
    job = wait_for(client, job_id, "done")
    assert job["urls"]["preview"] == f"/api/jobs/{job_id}/preview"
    assert job["urls"]["output"] is None  # el render completo aún no existe
    preview = client.get(f"/api/jobs/{job_id}/preview")
    assert preview.status_code == 200
    assert preview.content == b"fake-preview"
    assert engine.burn_calls == [3]


def test_render_completo_y_preview_no_se_pisan(start_app, sample_videos):
    engine = FakeEngine()
    engine.burn_ok = True
    client, _ = start_app(engine=engine)
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")
    client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": None})
    wait_for(client, job_id, "done")
    client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": 3})
    job = wait_for(client, job_id, "done")

    assert job["urls"]["output"] and job["urls"]["preview"]
    assert client.get(f"/api/jobs/{job_id}/output").content == b"fake-mp4"
    assert client.get(f"/api/jobs/{job_id}/preview").content == b"fake-preview"


@pytest.mark.parametrize("seconds", [1, 15])
def test_preview_acepta_los_limites_de_1_a_15_s(start_app, sample_videos, seconds):
    engine = FakeEngine()
    engine.burn_ok = True
    client, _ = start_app(engine=engine)
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")

    response = client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": seconds})

    assert response.status_code == 202
    wait_for(client, job_id, "done")


@pytest.mark.parametrize("seconds", [0.5, 16])
def test_preview_fuera_de_1_a_15_s_da_422(start_app, sample_videos, seconds):
    engine = FakeEngine()
    engine.burn_ok = True
    client, _ = start_app(engine=engine)
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")

    response = client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": seconds})

    assert response.status_code == 422


def test_job_inexistente_da_404(start_app):
    client, _ = start_app()
    missing = uuid.uuid4().hex

    assert client.get(f"/api/jobs/{missing}").status_code == 404
    assert client.get("/api/jobs/no-es-un-id").status_code == 404
    assert client.get(f"/api/jobs/{missing}/words").status_code == 404
    assert client.put(f"/api/jobs/{missing}/style", json={"preset": "ken_classic"}).status_code == 404
    assert client.post(f"/api/jobs/{missing}/render").status_code == 404


def test_archivo_que_aun_no_existe_da_404(start_app, sample_videos):
    client, _ = start_app()
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "ready")

    assert client.get(f"/api/jobs/{job_id}/output").status_code == 404
    assert client.get(f"/api/jobs/{job_id}/preview").status_code == 404


def test_input_responde_range_para_el_video(start_app, sample_videos):
    client, _ = start_app()
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]

    response = client.get(f"/api/jobs/{job_id}/input", headers={"Range": "bytes=0-99"})

    assert response.status_code == 206
    assert len(response.content) == 100
    assert response.headers["content-range"].startswith("bytes 0-99/")


def test_fuentes_devuelve_el_catalogo_del_motor_tal_cual(start_app):
    client, engine = start_app()

    response = client.get("/api/fonts")

    assert response.status_code == 200
    assert response.json() == engine.font_catalog()


def test_409_de_la_api_dice_el_estado_en_espanol(start_app, sample_videos):
    client, engine = start_app()
    engine.gate.clear()  # la transcripción se queda a medias
    job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
    wait_for(client, job_id, "transcribing", percent=42.0)

    response = client.put(f"/api/jobs/{job_id}/words", json=[{"text": "x", "start": 0, "end": 1}])

    assert response.status_code == 409
    assert response.json() == {"detail": "El job no admite este cambio en estado 'transcribiendo'."}
    engine.gate.set()
    wait_for(client, job_id, "ready")


@pytest.mark.parametrize("content_type", ["application/octet-stream", ""])
def test_content_type_generico_se_decide_por_el_contenido(start_app, sample_videos, content_type):
    client, _ = start_app()

    response = upload(client, sample_videos["sample.mp4"], content_type=content_type)

    assert response.status_code == 201
    wait_for(client, response.json()["job_id"], "ready")


@pytest.mark.parametrize("content_type", ["application/octet-stream", ""])
def test_content_type_generico_con_contenido_falso_da_400(start_app, tmp_path, content_type):
    client, _ = start_app()

    response = client.post("/api/jobs", files={"file": ("falso.mp4", b"esto no es un video", content_type)})

    assert response.status_code == 400
    assert "video" in response.json()["detail"]
    assert list((tmp_path / "data" / "jobs").iterdir()) == []
