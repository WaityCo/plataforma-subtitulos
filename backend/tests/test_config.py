"""Variables SUBS_* de despliegue: valores por defecto, sobrescritura, validación y efecto en la API."""

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import MB, PROJECT_ROOT, ConfigError, Settings, resolve_default_preset
from backend.tests import fakes
from backend.tests.fakes import FakeEngine
from backend.tests.helpers import upload, wait_for


def test_valores_por_defecto():
    settings = Settings.from_env({})

    assert settings.data_dir == PROJECT_ROOT / "data"
    assert settings.max_upload_bytes == 200 * MB
    assert settings.default_model == "small"
    assert settings.max_preview_seconds == 15
    assert settings.default_preset is None  # automático: ken_remedie si existe, si no ken_classic


def test_las_variables_sobrescriben_los_valores(tmp_path):
    settings = Settings.from_env(
        {
            "SUBS_DATA_DIR": str(tmp_path / "datos"),
            "SUBS_MAX_UPLOAD_MB": "50",
            "SUBS_DEFAULT_MODEL": "medium",
            "SUBS_MAX_PREVIEW_SECONDS": "6.5",
            "SUBS_DEFAULT_PRESET": "phrase_box",
        }
    )

    assert settings == Settings(
        data_dir=tmp_path / "datos",
        max_upload_bytes=50 * MB,
        default_model="medium",
        max_preview_seconds=6.5,
        default_preset="phrase_box",
    )


def test_ruta_relativa_cuelga_de_la_raiz_del_proyecto():
    assert Settings.from_env({"SUBS_DATA_DIR": "mis-datos"}).data_dir == PROJECT_ROOT / "mis-datos"


def test_valor_vacio_equivale_a_no_definir_la_variable():
    vacias = {"SUBS_MAX_UPLOAD_MB": "  ", "SUBS_DEFAULT_MODEL": "", "SUBS_DATA_DIR": "", "SUBS_DEFAULT_PRESET": " "}

    assert Settings.from_env(vacias) == Settings.from_env({})


@pytest.mark.parametrize(
    "name, value",
    [
        ("SUBS_MAX_UPLOAD_MB", "0"),
        ("SUBS_MAX_UPLOAD_MB", "mucho"),
        ("SUBS_MAX_UPLOAD_MB", "1.5"),
        ("SUBS_DEFAULT_MODEL", "gigante"),
        ("SUBS_MAX_PREVIEW_SECONDS", "0.5"),
        ("SUBS_MAX_PREVIEW_SECONDS", "nan"),
    ],
)
def test_valor_no_valido_detiene_la_configuracion(name, value):
    with pytest.raises(ConfigError, match=name):
        Settings.from_env({name: value})


def test_valor_no_valido_impide_crear_la_app(monkeypatch):
    monkeypatch.setenv("SUBS_MAX_UPLOAD_MB", "cero")

    with pytest.raises(ConfigError, match="SUBS_MAX_UPLOAD_MB"):
        create_app()


@pytest.mark.parametrize(
    "explicit, available, esperado",
    [
        (None, ["ken_classic", "phrase_box"], "ken_classic"),
        (None, ["ken_classic", "ken_remedie"], "ken_remedie"),
        ("phrase_box", ["ken_classic", "phrase_box", "ken_remedie"], "phrase_box"),
    ],
)
def test_resolve_default_preset(explicit, available, esperado):
    assert resolve_default_preset(explicit, available) == esperado


def test_default_preset_que_el_motor_no_tiene_detiene_el_arranque():
    with pytest.raises(ConfigError, match="SUBS_DEFAULT_PRESET"):
        resolve_default_preset("no_existe", ["ken_classic"])


def test_default_preset_automatico_usa_ken_remedie_cuando_existe(monkeypatch, tmp_path, sample_videos):
    monkeypatch.setitem(fakes.PRESETS, "ken_remedie", {"font_size": 80, "mode": "karaoke"})
    app = create_app(
        settings=Settings(data_dir=tmp_path / "datos"),
        engine=FakeEngine(),
        frontend_dir=tmp_path / "sin-frontend",
        presets_dir=tmp_path / "sin-presets",
    )

    with TestClient(app) as client:
        job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
        assert client.get(f"/api/jobs/{job_id}").json()["preset"] == "ken_remedie"
        wait_for(client, job_id, "ready")


def test_las_variables_llegan_a_la_api(monkeypatch, tmp_path, sample_videos):
    monkeypatch.setenv("SUBS_DATA_DIR", str(tmp_path / "datos"))
    monkeypatch.setenv("SUBS_MAX_UPLOAD_MB", "1")
    monkeypatch.setenv("SUBS_DEFAULT_MODEL", "tiny")
    monkeypatch.setenv("SUBS_MAX_PREVIEW_SECONDS", "6")
    monkeypatch.setenv("SUBS_DEFAULT_PRESET", "phrase_box")
    engine = FakeEngine()
    engine.burn_ok = True
    app = create_app(engine=engine, frontend_dir=tmp_path / "sin-frontend", presets_dir=tmp_path / "sin-presets")

    with TestClient(app) as client:
        grande = client.post("/api/jobs", files={"file": ("grande.mp4", b"\0" * (2 * MB), "video/mp4")})
        assert grande.status_code == 413
        job_id = upload(client, sample_videos["sample.mp4"]).json()["job_id"]
        wait_for(client, job_id, "ready")
        assert client.get(f"/api/jobs/{job_id}").json()["preset"] == "phrase_box"
        assert engine.model_sizes == ["tiny"]
        assert client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": 7}).status_code == 422
        assert client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": 6}).status_code == 202
        wait_for(client, job_id, "done")

    assert (tmp_path / "datos" / "jobs.db").is_file()


def test_con_el_motor_real_el_defecto_es_ken_remedie():
    from backend.engine_bridge import RealEngine

    ids = [preset["id"] for preset in RealEngine().list_presets()]

    assert resolve_default_preset(None, ids) == "ken_remedie"


@pytest.mark.parametrize(
    "raw, esperado",
    [
        (None, ()),
        ("", ()),
        ("http://localhost:5173", ("http://localhost:5173",)),
        (" https://a.example.com , http://localhost:5173/ ,", ("https://a.example.com", "http://localhost:5173")),
    ],
)
def test_cors_origins_se_leen_como_lista(raw, esperado):
    entorno = {} if raw is None else {"SUBS_CORS_ORIGINS": raw}

    assert Settings.from_env(entorno).cors_origins == esperado


@pytest.mark.parametrize(
    "raw",
    ["*", "localhost:5173", "ftp://a.example.com", "https://a.example.com/ruta", "https://a.example.com?x=1", "https://"],
)
def test_cors_origins_no_validos_detienen_el_arranque(raw):
    with pytest.raises(ConfigError, match="SUBS_CORS_ORIGINS"):
        Settings.from_env({"SUBS_CORS_ORIGINS": raw})


def test_api_key_vacia_no_pide_clave_y_los_espacios_se_quitan():
    assert Settings.from_env({"SUBS_API_KEY": "  "}).api_key is None
    assert Settings.from_env({"SUBS_API_KEY": " secreto "}).api_key == "secreto"
