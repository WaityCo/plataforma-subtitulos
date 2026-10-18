"""Clave de acceso (SUBS_API_KEY): X-Subs-Key en /api/* y /fonts/*. Con clave, la interfaz y la documentación no se sirven."""

import hmac
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from backend import acceso
from backend.app import create_app
from backend.config import Settings
from backend.tests.fakes import FakeEngine

CLAVE = "clave-de-prueba-larga"
RECHAZO = {"detail": "Falta la clave de acceso."}


@pytest.fixture
def cliente(tmp_path):
    settings = replace(Settings(data_dir=tmp_path / "data"), api_key=CLAVE)
    with TestClient(create_app(settings=settings, engine=FakeEngine())) as client:
        yield client


@pytest.mark.parametrize("ruta", ["/api", "/api/presets", "/api/config", "/api/jobs/" + "0" * 32, "/fonts/no-existe.ttf"])
def test_sin_clave_responde_401_con_el_detalle_del_contrato(cliente, ruta):
    response = cliente.get(ruta)

    assert response.status_code == 401
    assert response.json() == RECHAZO


def test_clave_incorrecta_responde_401(cliente):
    response = cliente.get("/api/presets", headers={"X-Subs-Key": "otra-clave"})

    assert response.status_code == 401
    assert response.json() == RECHAZO


def test_con_la_clave_correcta_la_api_responde(cliente):
    response = cliente.get("/api/presets", headers={"X-Subs-Key": CLAVE})

    assert response.status_code == 200


def test_las_fuentes_con_clave_pasan_al_montaje(cliente):
    response = cliente.get("/fonts/no-existe.ttf", headers={"X-Subs-Key": CLAVE})

    assert response.status_code == 404  # la clave pasó; el archivo no existe


def test_con_clave_la_interfaz_y_la_documentacion_no_se_sirven(cliente):
    for ruta in ("/", "/index.html", "/js/app.js", "/docs", "/redoc", "/openapi.json"):
        assert cliente.get(ruta).status_code == 404, ruta


def test_sin_clave_la_interfaz_y_la_documentacion_siguen_publicas(tmp_path):
    with TestClient(create_app(settings=Settings(data_dir=tmp_path / "data"), engine=FakeEngine())) as client:
        assert client.get("/").status_code == 200
        assert client.get("/index.html").status_code == 200
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200


def test_el_preflight_de_cors_no_pide_la_clave(tmp_path):
    settings = replace(Settings(data_dir=tmp_path / "data"), api_key=CLAVE, cors_origins=("http://localhost:5173",))
    with TestClient(create_app(settings=settings, engine=FakeEngine())) as client:
        response = client.options(
            "/api/presets", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"}
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_la_clave_se_compara_con_hmac_compare_digest(cliente, monkeypatch):
    llamadas = []
    original = hmac.compare_digest

    def espia(a, b):
        llamadas.append((a, b))
        return original(a, b)

    monkeypatch.setattr(hmac, "compare_digest", espia)
    cliente.get("/api/presets", headers={"X-Subs-Key": CLAVE})

    assert llamadas


def test_sin_la_variable_la_api_no_pide_clave(tmp_path):
    with TestClient(create_app(settings=Settings(data_dir=tmp_path / "data"), engine=FakeEngine())) as client:
        assert client.get("/api/presets").status_code == 200


@pytest.mark.parametrize(
    "ruta, protegida",
    [
        ("/api", True),
        ("/api/x", True),
        ("/fonts", True),
        ("/fonts/a.ttf", True),
        ("/", False),
        ("/index.html", False),
        ("/apia/x", False),
        ("/js/app.js", False),
    ],
)
def test_solo_la_api_y_las_fuentes_estan_protegidas(ruta, protegida):
    assert acceso.protegida(ruta) is protegida
