"""CORS para desarrollo local (SUBS_CORS_ORIGINS): sin orígenes, solo mismo origen; con orígenes, credenciales y
cabeceras expuestas."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.tests.fakes import FakeEngine
from backend.tests.helpers import upload, wait_for
from backend.tests.motor_real import MotorConTranscripcionFalsa, make_clip, requires_libass

ORIGEN = "http://localhost:5173"  # el frontend en desarrollo
CABECERAS_EXPUESTAS = ("X-Frame-Time", "X-Empty", "ETag")


@pytest.fixture
def cliente(tmp_path):
    settings = replace(Settings(data_dir=tmp_path / "data"), cors_origins=(ORIGEN,))
    with TestClient(create_app(settings=settings, engine=FakeEngine())) as client:
        yield client


def test_preflight_de_un_origen_permitido_da_credenciales(cliente):
    response = cliente.options("/api/presets", headers={"Origin": ORIGEN, "Access-Control-Request-Method": "GET"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGEN
    assert response.headers["access-control-allow-credentials"] == "true"


@pytest.mark.parametrize("metodo", ["GET", "POST", "PUT", "DELETE"])
def test_los_metodos_de_la_api_estan_permitidos(cliente, metodo):
    response = cliente.options("/api/jobs/x/words", headers={"Origin": ORIGEN, "Access-Control-Request-Method": metodo})

    assert metodo in response.headers["access-control-allow-methods"]


def test_las_cabeceras_que_usa_la_interfaz_estan_permitidas(cliente):
    response = cliente.options(
        "/api/jobs/x/words",
        headers={
            "Origin": ORIGEN,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type, if-none-match, range",
        },
    )

    permitidas = response.headers["access-control-allow-headers"].lower()
    assert all(cabecera in permitidas for cabecera in ("content-type", "if-none-match", "range"))


def test_una_respuesta_real_expone_las_cabeceras_de_la_miniatura(cliente):
    response = cliente.get("/api/presets", headers={"Origin": ORIGEN})

    assert response.headers["access-control-allow-origin"] == ORIGEN
    expuestas = response.headers["access-control-expose-headers"]
    assert all(cabecera in expuestas for cabecera in CABECERAS_EXPUESTAS)


def test_un_origen_no_permitido_no_recibe_cabecera_de_origen(cliente):
    response = cliente.get("/api/presets", headers={"Origin": "https://otro.example.test"})

    assert "access-control-allow-origin" not in response.headers


def test_sin_origenes_solo_hay_mismo_origen(tmp_path):
    with TestClient(create_app(settings=Settings(data_dir=tmp_path / "data"), engine=FakeEngine())) as client:
        response = client.get("/api/presets", headers={"Origin": ORIGEN})

    assert "access-control-allow-origin" not in response.headers


@requires_libass
def test_la_miniatura_con_origen_permitido_expone_sus_cabeceras(tmp_path):
    settings = replace(Settings(data_dir=tmp_path / "data"), cors_origins=(ORIGEN,))
    with TestClient(create_app(settings=settings, engine=MotorConTranscripcionFalsa())) as client:
        job_id = upload(client, make_clip(tmp_path, seconds=3)).json()["job_id"]
        wait_for(client, job_id, "ready")
        response = client.get(f"/api/jobs/{job_id}/preview-frame", headers={"Origin": ORIGEN})

    assert response.status_code == 200
    expuestas = response.headers["access-control-expose-headers"]
    assert all(cabecera in expuestas for cabecera in CABECERAS_EXPUESTAS)
