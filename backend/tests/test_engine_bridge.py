"""Contrato entre el backend y el motor real: presets con 'id', ValueError, libass y firma de burn."""

import pytest

from backend.engine_bridge import FONTS_DIR, RealEngine


def test_presets_del_motor_salen_con_id():
    presets = RealEngine().list_presets()

    assert "ken_classic" in [preset["id"] for preset in presets]
    for preset in presets:
        assert set(preset) == {"id", "label", "description", "style"}


def test_preset_desconocido_lanza_value_error():
    with pytest.raises(ValueError):
        RealEngine().resolve_style("no_existe", None)


def test_font_catalog_delega_en_el_motor(monkeypatch):
    from engine import textmetrics

    sentinel = [{"family": "Anton", "file": "Anton-Regular.ttf"}]
    monkeypatch.setattr(textmetrics, "font_catalog", lambda: sentinel)

    assert RealEngine().font_catalog() == sentinel


def test_fuentes_del_motor_real_llegan_tal_cual_por_la_api(start_app):
    client, _ = start_app(engine=RealEngine())

    response = client.get("/api/fonts")

    assert response.status_code == 200
    assert response.json() == RealEngine().font_catalog()


def test_burn_available_delega_en_el_motor(monkeypatch):
    from engine import burn as burn_module

    monkeypatch.setattr(burn_module, "is_available", lambda: True)
    assert RealEngine().burn_available() is True
    monkeypatch.setattr(burn_module, "is_available", lambda: False)
    assert RealEngine().burn_available() is False


def test_burn_llama_al_motor_con_el_texto_ass(monkeypatch, tmp_path):
    from engine import burn as burn_module

    calls = []
    monkeypatch.setattr(burn_module, "burn", lambda *args, **kwargs: calls.append((args, kwargs)))
    ass_path = tmp_path / "subtitles.ass"
    ass_path.write_text("[Script Info]\n", encoding="utf-8")

    RealEngine().burn(
        video_path=tmp_path / "in.mp4",
        ass_path=ass_path,
        output_path=tmp_path / "out.mp4",
        preview_seconds=3,
    )

    args, kwargs = calls[0]
    assert args == (tmp_path / "in.mp4", "[Script Info]\n", tmp_path / "out.mp4", FONTS_DIR)
    assert kwargs == {"preview_seconds": 3, "progress": None, "overlays": ()}


def test_burn_con_gancho_dibuja_el_png_en_el_tamano_del_job(monkeypatch, tmp_path):
    from engine import burn as burn_module
    from engine import hook as hook_module

    calls = []
    monkeypatch.setattr(burn_module, "burn", lambda *args, **kwargs: calls.append(kwargs))
    dibujados = []
    overlay = (tmp_path / "hook" / "hook_pill.png", 0.0, 2.0, 10, 20)
    monkeypatch.setattr(
        hook_module, "render_hook", lambda *args, **kwargs: dibujados.append((args, kwargs)) or [overlay]
    )
    ass_path = tmp_path / "subtitles.ass"
    ass_path.write_text("[Script Info]\n", encoding="utf-8")
    hook = {"headline": "Hola", "duration_s": 2.0}

    RealEngine().burn(
        video_path=tmp_path / "in.mp4", ass_path=ass_path, output_path=tmp_path / "out.mp4",
        hook=hook, width=720, height=1280,
    )

    assert dibujados == [((hook, 720, 1280), {"out_dir": tmp_path / "hook"})]
    assert calls[0]["overlays"] == [overlay]


def test_burn_con_gancho_sin_tamano_es_un_error(tmp_path):
    ass_path = tmp_path / "subtitles.ass"
    ass_path.write_text("[Script Info]\n", encoding="utf-8")

    with pytest.raises(ValueError, match="width y height"):
        RealEngine().burn(
            video_path=tmp_path / "in.mp4", ass_path=ass_path, output_path=tmp_path / "out.mp4",
            hook={"headline": "Hola", "duration_s": 2.0},
        )


def test_build_segments_del_motor_real():
    engine = RealEngine()
    style = engine.resolve_style("ken_classic", None)
    words = [
        {"text": "hola", "start": 0.0, "end": 0.5, "emph": None},
        {"text": "mundo", "start": 0.5, "end": 1.0, "emph": None},
    ]

    segments = engine.build_segments(words, style, 720, 1280)

    assert segments
    assert {"start", "end", "lines", "fit", "windows"} <= set(segments[0])
