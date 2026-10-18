"""GET /api/config: lo que la interfaz lee para mostrar el límite real, el preset por defecto y la versión."""

from backend import __version__
from backend.config import MB


def test_config_devuelve_limite_en_mb_y_en_bytes_preset_y_version(start_app):
    client, _ = start_app(max_upload_bytes=100 * MB)

    response = client.get("/api/config")

    assert response.status_code == 200
    assert response.json() == {
        "max_upload_mb": 100,
        "max_upload_bytes": 100 * MB,
        "default_preset": "ken_classic",
        "version": __version__,
    }
