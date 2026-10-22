"""Modo local: lo que sale directo del Mac no pide clave y recibe la interfaz. Lo que llega por el túnel sigue igual que antes."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from backend.acceso import es_local
from backend.app import create_app
from backend.config import LOCAL_CHUNK_BYTES, MB, Settings
from backend.tests.fakes import FakeEngine

CLAVE = "clave-de-prueba-larga"
TUNEL = "ejemplo-prueba.trycloudflare.com"  # el Host que Cloudflare conserva al reenviar por el túnel rápido
PUBLICO = "https://subtitulos.example.workers.dev"  # el sitio público que puede consultar el ping
LOCAL = ("127.0.0.1", 50000)
REMOTO = ("203.0.113.7", 50000)  # dirección de documentación (RFC 5737)
CABECERAS_DE_CLOUDFLARE = {"cf-connecting-ip": "203.0.113.7", "cf-ray": "a4ea70dbd92a0f0f-SCL", "cdn-loop": "cloudflare; loops=1"}
CABECERA_TUNEL = {"host": TUNEL, "X-Subs-Key": CLAVE}


def _scope(host="127.0.0.1:8765", client=LOCAL, origin=None, extra=()):
    cabeceras = [(b"host", host.encode())]
    if origin is not None:
        cabeceras.append((b"origin", origin.encode()))
    cabeceras.extend((nombre.encode(), valor.encode()) for nombre, valor in extra)
    return {"type": "http", "path": "/api/presets", "client": client, "headers": cabeceras}


@pytest.fixture
def cliente(tmp_path):
    settings = replace(Settings(data_dir=tmp_path / "data"), api_key=CLAVE, public_origins=(PUBLICO,))
    with TestClient(create_app(settings=settings, engine=FakeEngine()), base_url="http://127.0.0.1:8765", client=LOCAL) as client:
        yield client


# Detección

@pytest.mark.parametrize("host, client", [("127.0.0.1:8765", LOCAL), ("localhost:8765", LOCAL), ("[::1]:8765", ("::1", 50000))])
def test_conexion_directa_al_propio_mac_es_local(host, client):
    assert es_local(_scope(host=host, client=client))


def test_cliente_remoto_no_es_local():
    assert not es_local(_scope(client=REMOTO))


def test_host_del_tunel_no_es_local_aunque_el_cliente_sea_loopback():
    assert not es_local(_scope(host=TUNEL))


def test_dos_cabeceras_host_no_son_local():
    assert not es_local(_scope(extra=[("host", "127.0.0.1:8765")]))


@pytest.mark.parametrize(
    "nombre",
    ["cf-connecting-ip", "cf-ray", "cf-visitor", "cdn-loop", "x-forwarded-for", "x-forwarded-proto", "forwarded", "x-real-ip", "true-client-ip"],
)
def test_cualquier_cabecera_de_proxy_quita_el_modo_local(nombre):
    assert not es_local(_scope(extra=[(nombre, "1")]))


def test_origin_del_propio_servidor_es_local():
    assert es_local(_scope(origin="http://127.0.0.1:8765"))
    assert es_local(_scope(host="localhost:8765", origin="http://localhost:8765"))


@pytest.mark.parametrize("origin", ["https://ejemplo.test", "http://localhost:3000", "http://127.0.0.1:9999", "null"])
def test_origin_ajeno_no_es_local(origin):
    assert not es_local(_scope(origin=origin))


# Clave e interfaz

def test_local_sin_clave_responde_la_api(cliente):
    assert cliente.get("/api/presets").status_code == 200


def test_local_sirve_la_interfaz_y_las_fuentes_sin_clave(cliente):
    assert cliente.get("/").status_code == 200
    assert cliente.get("/fonts/Anton-Regular.ttf").status_code == 200


def test_local_con_clave_incorrecta_tambien_entra(cliente):
    assert cliente.get("/api/presets", headers={"X-Subs-Key": "otra-clave"}).status_code == 200


def test_por_el_tunel_sin_clave_la_api_pide_clave_y_la_interfaz_no_existe(cliente):
    assert cliente.get("/api/presets", headers={"host": TUNEL}).status_code == 401
    assert cliente.get("/fonts/Anton-Regular.ttf", headers={"host": TUNEL}).status_code == 401
    assert cliente.get("/", headers={"host": TUNEL}).status_code == 404


def test_por_el_tunel_con_clave_entra_a_la_api_pero_no_ve_la_interfaz(cliente):
    assert cliente.get("/api/presets", headers=CABECERA_TUNEL).status_code == 200
    assert cliente.get("/", headers=CABECERA_TUNEL).status_code == 404


def test_una_cabecera_de_cloudflare_quita_el_modo_local_aunque_el_host_sea_local(cliente):
    assert cliente.get("/api/presets", headers=CABECERAS_DE_CLOUDFLARE).status_code == 401
    assert cliente.get("/", headers=CABECERAS_DE_CLOUDFLARE).status_code == 404


def test_otra_web_del_navegador_no_usa_la_api_local_sin_clave(cliente):
    cabecera = {"Origin": "https://ejemplo.test"}
    assert cliente.get("/api/presets", headers=cabecera).status_code == 401
    assert cliente.post("/api/jobs", headers=cabecera).status_code == 401


def test_la_documentacion_no_se_publica_con_clave(cliente):
    for ruta in ("/docs", "/openapi.json"):
        assert cliente.get(ruta).status_code == 404
        assert cliente.get(ruta, headers={"host": TUNEL}).status_code == 404


# Configuración y subidas

def test_config_desde_el_mac_trozos_de_64_mb_y_un_envio(cliente):
    datos = cliente.get("/api/config").json()

    assert datos["local"] is True
    assert datos["chunk_bytes"] == LOCAL_CHUNK_BYTES
    assert datos["upload_concurrency"] == 1


def test_config_por_el_tunel_trozos_de_8_mb_y_tres_envios(cliente):
    datos = cliente.get("/api/config", headers=CABECERA_TUNEL).json()

    assert datos["local"] is False
    assert datos["chunk_bytes"] == 8 * MB
    assert datos["upload_concurrency"] == 3


def test_desde_el_mac_la_subida_admite_trozos_de_mas_de_8_mb(cliente):
    alta = cliente.post("/api/uploads", json={"filename": "video.mp4", "size": 100 * MB, "content_type": "video/mp4"})

    assert alta.status_code == 201
    datos = alta.json()
    assert datos["chunk_size"] == LOCAL_CHUNK_BYTES
    assert datos["total_chunks"] == 2
    trozo = cliente.put(f"/api/uploads/{datos['upload_id']}/chunks/0", content=b"x" * (9 * MB))
    assert trozo.status_code == 200


def test_por_el_tunel_la_subida_sigue_en_trozos_de_8_mb(cliente):
    alta = cliente.post(
        "/api/uploads", json={"filename": "video.mp4", "size": 100 * MB, "content_type": "video/mp4"}, headers=CABECERA_TUNEL
    )

    datos = alta.json()
    assert datos["chunk_size"] == 8 * MB
    trozo = cliente.put(f"/api/uploads/{datos['upload_id']}/chunks/0", content=b"x" * (9 * MB), headers=CABECERA_TUNEL)
    assert trozo.status_code == 413


# Ping

def test_el_preflight_del_ping_da_permiso_de_red_privada_al_sitio_publico(cliente):
    respuesta = cliente.options(
        "/api/local-ping",
        headers={"Origin": PUBLICO, "Access-Control-Request-Method": "GET", "Access-Control-Request-Private-Network": "true"},
    )

    assert respuesta.status_code == 204
    assert respuesta.headers["access-control-allow-origin"] == PUBLICO
    assert respuesta.headers["access-control-allow-private-network"] == "true"
    assert "GET" in respuesta.headers["access-control-allow-methods"]


def test_el_ping_responde_ok_con_cors_para_el_sitio_publico(cliente):
    respuesta = cliente.get("/api/local-ping", headers={"Origin": PUBLICO})

    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True}
    assert respuesta.headers["access-control-allow-origin"] == PUBLICO
    assert respuesta.headers["cache-control"] == "no-store"


def test_el_ping_sin_origen_responde_ok_sin_cors(cliente):
    respuesta = cliente.get("/api/local-ping")

    assert respuesta.json() == {"ok": True}
    assert "access-control-allow-origin" not in respuesta.headers


def test_el_ping_no_da_cors_a_otros_origenes(cliente):
    cabecera = {"Origin": "https://ejemplo.test"}
    assert "access-control-allow-origin" not in cliente.get("/api/local-ping", headers=cabecera).headers

    preflight = cliente.options("/api/local-ping", headers={**cabecera, "Access-Control-Request-Method": "GET"})
    assert preflight.status_code == 204
    assert "access-control-allow-private-network" not in preflight.headers


def test_el_ping_no_existe_por_el_tunel(cliente):
    assert cliente.get("/api/local-ping", headers=CABECERA_TUNEL).status_code == 404
    assert cliente.get("/api/local-ping", headers=CABECERAS_DE_CLOUDFLARE).status_code == 404


def test_el_ping_solo_admite_get_y_preflight(cliente):
    assert cliente.post("/api/local-ping").status_code == 405
