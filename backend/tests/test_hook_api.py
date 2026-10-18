"""Gancho titular: validación, guardado (PUT /hook y POST /render), paso al quemado y a las miniaturas."""

import json
import uuid

import pytest

from backend import thumbs
from backend.jobs import JobManager
from backend.tests.fakes import FakeEngine
from backend.tests.helpers import upload, wait_for
from backend.tests.motor_real import MotorConTranscripcionFalsa, changed_pixels, make_clip, requires_libass

HOOK = {
    "headline": "¿Quieres ganar dinero online?",
    "kicker": "NOTICIA",
    "news_title": "ÚLTIMA HORA",
    "news_subtitle": "Lo que nadie te cuenta",
    "duration_s": 3,
}
INVALIDOS = [
    {"duration_s": 3},  # sin titular
    {"headline": "   ", "duration_s": 3},  # titular en blanco
    {"headline": "x" * 201, "duration_s": 3},  # más de 200 caracteres
    {"headline": "ok", "kicker": "k" * 201, "duration_s": 3},
    {"headline": "ok", "news_title": "t" * 201, "duration_s": 3},
    {"headline": "ok", "news_subtitle": "s" * 201, "duration_s": 3},
    {"headline": "ok", "duration_s": 0.4},  # por debajo de 0.5 s
    {"headline": "ok", "duration_s": 10.5},  # por encima de 10 s
    {"headline": "ok"},  # sin duración
    {"headline": "ok", "duration_s": 3, "titulo": "typo"},  # campo desconocido
    "texto suelto",  # no es un objeto
]


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    return make_clip(tmp_path_factory.mktemp("gancho"), seconds=5)


def _motor_con_quemado():
    engine = FakeEngine()
    engine.burn_ok = True  # sin libass el render responde 501 antes de llegar al motor
    return engine


def _job(client, clip):
    job_id = upload(client, clip).json()["job_id"]
    wait_for(client, job_id, "ready")
    return job_id


def _render(client, job_id, **body):
    return client.post(f"/api/jobs/{job_id}/render", json=body)


def _put_hook(client, job_id, hook):
    # json=None en httpx no envía cuerpo: el null se manda como texto JSON.
    return client.put(
        f"/api/jobs/{job_id}/hook", content=json.dumps(hook), headers={"content-type": "application/json"}
    )


def _frame(client, job_id, at):
    return client.get(f"/api/jobs/{job_id}/preview-frame", params={"preset": "ken_classic", "t": at})


def test_render_sin_gancho_usa_el_guardado_o_null(start_app, clip):
    engine = _motor_con_quemado()
    client, _ = start_app(engine=engine)
    job_id = _job(client, clip)

    assert _render(client, job_id, preview_seconds=None).status_code == 202

    assert wait_for(client, job_id, "done")["hook"] is None
    assert engine.burn_hooks == [None]


def test_render_sin_gancho_conserva_el_guardado(start_app, clip):
    engine = _motor_con_quemado()
    client, _ = start_app(engine=engine)
    job_id = _job(client, clip)
    _render(client, job_id, preview_seconds=None, hook=HOOK)
    wait_for(client, job_id, "done")

    _render(client, job_id, preview_seconds=None)

    assert wait_for(client, job_id, "done")["hook"] == HOOK
    assert engine.burn_hooks == [HOOK, HOOK]


def test_render_con_gancho_reemplaza_y_guarda(start_app, clip):
    engine = _motor_con_quemado()
    client, _ = start_app(engine=engine)
    job_id = _job(client, clip)
    _render(client, job_id, preview_seconds=None, hook=HOOK)
    wait_for(client, job_id, "done")
    nuevo = {"headline": "Otro titular", "kicker": None, "news_title": None, "news_subtitle": None, "duration_s": 1.5}

    _render(client, job_id, preview_seconds=None, hook={"headline": "Otro titular", "duration_s": 1.5})

    assert wait_for(client, job_id, "done")["hook"] == nuevo
    assert engine.burn_hooks[-1] == nuevo


def test_el_hook_llega_al_quemado_del_preview_y_del_render(start_app, clip):
    engine = _motor_con_quemado()
    client, _ = start_app(engine=engine)
    job_id = _job(client, clip)

    _render(client, job_id, preview_seconds=3, hook=HOOK)
    wait_for(client, job_id, "done")
    _render(client, job_id, preview_seconds=None)  # sin hook: usa el guardado
    wait_for(client, job_id, "done")

    assert engine.burn_calls == [3, None]
    assert engine.burn_hooks == [HOOK, HOOK]


def test_put_hook_guarda_sin_renderizar(start_app, clip):
    client, _ = start_app(engine=_motor_con_quemado())
    job_id = _job(client, clip)

    response = _put_hook(client, job_id, HOOK)

    assert response.status_code == 200
    assert response.json() == HOOK
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["hook"] == HOOK
    assert job["status"] == "ready"  # no encola nada


def test_put_hook_null_quita_el_guardado(start_app, clip):
    engine = _motor_con_quemado()
    client, _ = start_app(engine=engine)
    job_id = _job(client, clip)
    _put_hook(client, job_id, HOOK)

    response = _put_hook(client, job_id, None)

    assert response.status_code == 200
    assert response.json() is None
    assert client.get(f"/api/jobs/{job_id}").json()["hook"] is None
    _render(client, job_id, preview_seconds=None)
    wait_for(client, job_id, "done")
    assert engine.burn_hooks == [None]


@pytest.mark.parametrize("hook", INVALIDOS)
def test_put_hook_422_si_no_es_valido(start_app, clip, hook):
    client, _ = start_app(engine=_motor_con_quemado())
    job_id = _job(client, clip)

    response = _put_hook(client, job_id, hook)

    assert response.status_code == 422
    assert response.json()["detail"]
    assert client.get(f"/api/jobs/{job_id}").json()["hook"] is None


@pytest.mark.parametrize("hook", INVALIDOS)
def test_render_422_si_el_hook_no_es_valido(start_app, clip, hook):
    client, _ = start_app(engine=_motor_con_quemado())
    job_id = _job(client, clip)

    response = _render(client, job_id, preview_seconds=None, hook=hook)

    assert response.status_code == 422
    assert response.json()["detail"]
    assert client.get(f"/api/jobs/{job_id}").json()["hook"] is None


def test_put_hook_sin_cuerpo_responde_422(start_app, clip):
    client, _ = start_app(engine=_motor_con_quemado())
    job_id = _job(client, clip)

    assert client.put(f"/api/jobs/{job_id}/hook").status_code == 422


def test_put_hook_409_mientras_el_job_transcribe(start_app, clip):
    engine = FakeEngine()
    client, _ = start_app(engine=engine)
    engine.gate.clear()  # la transcripción queda a medias
    job_id = upload(client, clip).json()["job_id"]
    wait_for(client, job_id, "transcribing", percent=42.0)

    assert _put_hook(client, job_id, HOOK).status_code == 409


def test_put_hook_404_con_job_inexistente(start_app):
    client, _ = start_app(engine=_motor_con_quemado())

    assert _put_hook(client, uuid.uuid4().hex, HOOK).status_code == 404


@pytest.mark.parametrize("duracion", [0.5, 10])
def test_hook_en_los_limites_se_acepta(start_app, clip, duracion):
    client, _ = start_app(engine=_motor_con_quemado())
    job_id = _job(client, clip)
    limite = {"headline": "h" * 200, "kicker": "k" * 200, "news_title": "t" * 200, "news_subtitle": "s" * 200}

    response = _put_hook(client, job_id, {**limite, "duration_s": duracion})

    assert response.status_code == 200
    assert client.get(f"/api/jobs/{job_id}").json()["hook"]["duration_s"] == duracion


def test_el_hook_sobrevive_a_un_gestor_nuevo_sobre_la_misma_base(start_app, clip):
    client, _ = start_app(engine=_motor_con_quemado())
    job_id = _job(client, clip)
    _put_hook(client, job_id, HOOK)

    gestor = JobManager(client.app.state.settings, FakeEngine())  # no arranca el worker: solo lee la base

    assert gestor.get_status(job_id)["hook"] == HOOK


@requires_libass
def test_el_gancho_sale_en_el_fotograma_mientras_dura(start_app, clip, tmp_path):
    client, _ = start_app(engine=MotorConTranscripcionFalsa())
    job_id = _job(client, clip)
    video = client.app.state.jobs.job_dir(job_id) / "input.mp4"
    _put_hook(client, job_id, {"headline": "Hola gancho", "duration_s": 2})

    con = _frame(client, job_id, 1.0)
    tarde = _frame(client, job_id, 3.0)
    _put_hook(client, job_id, None)
    sin = _frame(client, job_id, 1.0)

    assert con.status_code == tarde.status_code == sin.status_code == 200
    assert con.headers["etag"] != sin.headers["etag"]  # la clave incluye el gancho
    (tmp_path / "con.jpg").write_bytes(con.content)
    (tmp_path / "sin.jpg").write_bytes(sin.content)
    (tmp_path / "tarde.jpg").write_bytes(tarde.content)
    thumbs.render_frame(video, None, 3.0, 360, tmp_path / "ref3.jpg")

    assert changed_pixels(tmp_path / "con.jpg", tmp_path / "sin.jpg") > 1000  # a 1 s la pastilla está en pantalla
    assert changed_pixels(tmp_path / "tarde.jpg", tmp_path / "ref3.jpg") <= 20  # pasados 2 s no hay gancho


@requires_libass
def test_el_automatico_evita_la_pastilla_si_hay_subtitulos_despues(start_app, clip):
    client, engine = start_app(engine=MotorConTranscripcionFalsa())
    engine.words = [  # una frase antes del gancho (puntúa más) y una palabra después de él
        {"text": "consejo", "start": 0.5, "end": 0.9},
        {"text": "sencillo", "start": 0.9, "end": 1.3},
        {"text": "tras", "start": 2.5, "end": 3.0},
    ]
    job_id = _job(client, clip)
    _put_hook(client, job_id, {"headline": "Hola gancho", "duration_s": 2})

    automatico = client.get(f"/api/jobs/{job_id}/preview-frame", params={"preset": "ken_classic"})

    assert automatico.status_code == 200
    assert float(automatico.headers["x-frame-time"]) >= 2.0  # el instante cae después del gancho
