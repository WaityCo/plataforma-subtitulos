"""Archivos estáticos y ficheros de presets: frontend, fuentes y /api/stopwords."""

from backend.engine_bridge import FONTS_DIR


def _frontend(folder):
    (folder / "js").mkdir(parents=True)
    (folder / "css").mkdir()
    (folder / "index.html").write_text("<!doctype html><title>Subs</title>", encoding="utf-8")
    (folder / "js" / "app.js").write_text("console.log('ok');", encoding="utf-8")
    (folder / "css" / "app.css").write_text("body {}", encoding="utf-8")
    return folder


def test_frontend_se_sirve_en_raiz(start_app, tmp_path):
    client, _ = start_app(frontend_dir=_frontend(tmp_path / "frontend"))

    root = client.get("/")

    assert root.status_code == 200
    assert "<title>Subs</title>" in root.text
    assert client.get("/js/app.js").status_code == 200
    assert client.get("/css/app.css").status_code == 200


def test_frontend_inexistente_no_impide_arrancar(start_app, tmp_path):
    client, _ = start_app(frontend_dir=tmp_path / "no-existe")

    assert client.get("/api/presets").status_code == 200
    assert client.get("/").status_code == 404


def test_fuentes_se_sirven_en_fonts(start_app):
    client, _ = start_app()
    font = FONTS_DIR / "Anton-Regular.ttf"

    response = client.get("/fonts/Anton-Regular.ttf")

    assert response.status_code == 200
    assert response.content == font.read_bytes()


def test_stopwords_404_mientras_no_exista(start_app, tmp_path):
    presets = tmp_path / "presets"
    presets.mkdir()
    client, _ = start_app(presets_dir=presets)

    assert client.get("/api/stopwords").status_code == 404


def test_stopwords_devuelve_el_archivo_tal_cual(start_app, tmp_path):
    presets = tmp_path / "presets"
    presets.mkdir()
    (presets / "stopwords.json").write_text('{"es": ["de", "la", "que"]}', encoding="utf-8")
    client, _ = start_app(presets_dir=presets)

    response = client.get("/api/stopwords")

    assert response.status_code == 200
    assert response.json() == {"es": ["de", "la", "que"]}
    assert response.headers["content-type"].startswith("application/json")
