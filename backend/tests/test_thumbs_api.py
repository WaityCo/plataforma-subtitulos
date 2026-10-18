"""GET /api/jobs/{id}/preview-frame: estados, validación, cabeceras, caché, invalidación y X-Empty."""

import uuid

import pytest

from backend import thumbs
from backend.tests.helpers import upload, wait_for
from backend.tests.motor_real import MotorConTranscripcionFalsa, make_clip, requires_libass


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    return make_clip(tmp_path_factory.mktemp("miniaturas"), seconds=5)


def _job(client, clip, words=None):
    if words is not None:
        client.app.state.jobs.engine.words = words  # la transcripción falsa devuelve estas palabras
    job_id = upload(client, clip).json()["job_id"]
    wait_for(client, job_id, "ready")
    return job_id


def test_409_mientras_el_job_no_esta_listo(start_app, clip):
    client, engine = start_app(engine=MotorConTranscripcionFalsa())
    engine.burn_available = lambda: True  # esta prueba mide el estado del job, no si hay libass
    engine.gate.clear()  # la transcripción queda a medias
    job_id = upload(client, clip).json()["job_id"]
    wait_for(client, job_id, "transcribing", percent=42.0)

    assert client.get(f"/api/jobs/{job_id}/preview-frame").status_code == 409
    assert client.get(f"/api/jobs/{uuid.uuid4().hex}/preview-frame").status_code == 404


@pytest.mark.parametrize(
    "query",
    [{"preset": "no_existe"}, {"w": 2000}, {"w": 4}, {"t": 99}, {"t": -1}, {"overrides": "no-json"}],
)
def test_422_con_estilo_o_parametros_no_validos(start_app, clip, query):
    client, _ = start_app(engine=MotorConTranscripcionFalsa())
    job_id = _job(client, clip)

    assert client.get(f"/api/jobs/{job_id}/preview-frame", params=query).status_code == 422


@requires_libass
def test_jpeg_con_cabeceras_de_cache_y_tamano_por_defecto(start_app, clip):
    client, _ = start_app(engine=MotorConTranscripcionFalsa())
    job_id = _job(client, clip)

    response = client.get(f"/api/jobs/{job_id}/preview-frame", params={"preset": "ken_classic"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content[:2] == b"\xff\xd8"
    assert response.headers["cache-control"] == "private, max-age=3600"
    assert response.headers["etag"].startswith('"') and response.headers["etag"].endswith('"')
    assert float(response.headers["x-frame-time"]) > 0
    assert "x-empty" not in response.headers


@requires_libass
def test_304_si_el_cliente_ya_tiene_la_miniatura(start_app, clip):
    client, _ = start_app(engine=MotorConTranscripcionFalsa())
    job_id = _job(client, clip)
    primera = client.get(f"/api/jobs/{job_id}/preview-frame", params={"w": 200})

    segunda = client.get(
        f"/api/jobs/{job_id}/preview-frame", params={"w": 200}, headers={"If-None-Match": primera.headers["etag"]}
    )

    assert segunda.status_code == 304
    assert segunda.content == b""


@requires_libass
def test_la_cache_evita_renderizar_otra_vez(start_app, clip, monkeypatch):
    client, _ = start_app(engine=MotorConTranscripcionFalsa())
    job_id = _job(client, clip)
    llamadas = []
    original = thumbs.render_frame
    monkeypatch.setattr(thumbs, "render_frame", lambda *args, **kwargs: (llamadas.append(args), original(*args, **kwargs))[1])

    client.get(f"/api/jobs/{job_id}/preview-frame", params={"w": 180})
    client.get(f"/api/jobs/{job_id}/preview-frame", params={"w": 180})

    assert len(llamadas) == 1


@requires_libass
def test_put_words_invalida_la_cache(start_app, clip, monkeypatch):
    client, _ = start_app(engine=MotorConTranscripcionFalsa())
    job_id = _job(client, clip)
    llamadas = []
    original = thumbs.render_frame
    monkeypatch.setattr(thumbs, "render_frame", lambda *args, **kwargs: (llamadas.append(args), original(*args, **kwargs))[1])
    client.get(f"/api/jobs/{job_id}/preview-frame", params={"w": 160})

    client.put(f"/api/jobs/{job_id}/words", json=[{"text": "nuevo", "start": 0.0, "end": 1.0}])
    assert not (client.app.state.jobs.job_dir(job_id) / thumbs.THUMBS_DIR).exists()
    client.get(f"/api/jobs/{job_id}/preview-frame", params={"w": 160})

    assert len(llamadas) == 2


@requires_libass
def test_sin_palabras_va_sin_subtitulos_y_con_x_empty(start_app, clip):
    client, _ = start_app(engine=MotorConTranscripcionFalsa())
    job_id = _job(client, clip, words=[])

    response = client.get(f"/api/jobs/{job_id}/preview-frame")

    assert response.status_code == 200
    assert response.headers["x-empty"] == "1"
    assert response.content[:2] == b"\xff\xd8"


@requires_libass
def test_t_explicito_se_devuelve_y_el_automatico_cae_dentro_del_video(start_app, clip):
    client, _ = start_app(engine=MotorConTranscripcionFalsa())
    job_id = _job(client, clip)

    explicito = client.get(f"/api/jobs/{job_id}/preview-frame", params={"t": 1.5})
    automatico = client.get(f"/api/jobs/{job_id}/preview-frame", params={"preset": "phrase_box"})

    assert explicito.headers["x-frame-time"] == "1.500"
    assert 0 < float(automatico.headers["x-frame-time"]) < 5.0


@requires_libass
def test_presets_distintos_dan_miniaturas_distintas(start_app, clip):
    client, _ = start_app(engine=MotorConTranscripcionFalsa())
    job_id = _job(client, clip)

    ken = client.get(f"/api/jobs/{job_id}/preview-frame", params={"preset": "ken_classic"})
    phrase = client.get(f"/api/jobs/{job_id}/preview-frame", params={"preset": "phrase_box"})

    assert ken.headers["etag"] != phrase.headers["etag"]


@requires_libass
def test_fallo_de_ffmpeg_responde_500_con_detail_en_json(start_app, clip):
    client, _ = start_app(engine=MotorConTranscripcionFalsa())
    job_id = _job(client, clip)
    video = client.app.state.jobs.job_dir(job_id) / "input.mp4"
    video.write_bytes(b"esto no es un video" * 200)  # el video del job queda dañado

    response = client.get(f"/api/jobs/{job_id}/preview-frame", params={"t": 1.0})

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    assert response.json()["detail"].startswith("ffmpeg no pudo sacar el fotograma")
    assert not list((client.app.state.jobs.job_dir(job_id) / thumbs.THUMBS_DIR).glob("*.jpg"))


@requires_libass
def test_instante_sin_fotograma_responde_422_con_detail(start_app, clip, tmp_path):
    client, _ = start_app(engine=MotorConTranscripcionFalsa())
    job_id = _job(client, clip)
    corto = make_clip(tmp_path, seconds=1)
    video = client.app.state.jobs.job_dir(job_id) / "input.mp4"
    video.write_bytes(corto.read_bytes())  # dura 1 s, pero el job guardó 5 s

    response = client.get(f"/api/jobs/{job_id}/preview-frame", params={"t": 3.0})

    assert response.status_code == 422
    assert response.json()["detail"].startswith("No hay fotograma en t=3.000 s")


def test_preview_sin_libass_responde_501_igual_que_el_render(start_app, clip):
    client, engine = start_app(engine=MotorConTranscripcionFalsa())
    engine.burn_available = lambda: False  # FFmpeg sin libass
    job_id = _job(client, clip)

    preview = client.get(f"/api/jobs/{job_id}/preview-frame")
    render = client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": None})

    assert preview.status_code == 501
    assert render.status_code == 501
    assert preview.json() == render.json()
    assert "libass" in preview.json()["detail"]
