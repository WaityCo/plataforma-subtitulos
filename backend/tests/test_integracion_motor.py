"""Integración con el motor real: el quemado usa FFmpeg de verdad. La transcripción va falsa, sin whisper.

Se omite si engine.burn.is_available() es falso (el FFmpeg resuelto no tiene libass).
"""

import json
import subprocess

import pytest

from backend import thumbs
from backend.tests.helpers import upload, wait_for
from backend.tests.motor_real import MotorConTranscripcionFalsa, changed_pixels, make_clip, requires_libass


def _probe(path) -> dict:
    from engine.ffbin import ffprobe_bin

    out = subprocess.run(
        [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    data = json.loads(out)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    return {"width": int(video["width"]), "height": int(video["height"]), "duration": float(data["format"]["duration"])}


@pytest.fixture(scope="module")
def clip_5s(tmp_path_factory):
    """Video de 5 s con ffmpeg lavfi: hace falta más largo que el preview de 3 s."""
    return make_clip(tmp_path_factory.mktemp("clip"), seconds=5, name="cinco.mp4")


@requires_libass
def test_quema_render_completo_y_preview_de_3_s(start_app, clip_5s, tmp_path):
    client, _ = start_app(engine=MotorConTranscripcionFalsa())
    job_id = upload(client, clip_5s).json()["job_id"]
    wait_for(client, job_id, "ready")

    assert client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": None}).status_code == 202
    job = wait_for(client, job_id, "done")
    full = client.get(job["urls"]["output"])
    assert full.status_code == 200
    full_path = tmp_path / "output.mp4"
    full_path.write_bytes(full.content)
    info = _probe(full_path)
    assert (info["width"], info["height"]) == (720, 1280)
    assert 4.8 <= info["duration"] <= 5.3

    assert client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": 3}).status_code == 202
    job = wait_for(client, job_id, "done")
    preview = client.get(job["urls"]["preview"])
    assert preview.status_code == 200
    preview_path = tmp_path / "preview.mp4"
    preview_path.write_bytes(preview.content)
    assert 2.8 <= _probe(preview_path)["duration"] <= 3.3


@requires_libass
def test_segments_reales_de_un_job_con_ken_remedie(start_app, clip_5s):
    client, _ = start_app(engine=MotorConTranscripcionFalsa())
    job_id = upload(client, clip_5s, preset="ken_remedie").json()["job_id"]
    wait_for(client, job_id, "ready")

    response = client.get(f"/api/jobs/{job_id}/segments")

    assert response.status_code == 200
    segments = response.json()
    assert segments
    assert all({"start", "end", "lines", "fit", "windows"} <= set(segment) for segment in segments)


@requires_libass
def test_el_subtitulo_aparece_en_el_instante_pedido_y_en_el_automatico(start_app, clip_5s, tmp_path):
    client, _ = start_app(engine=MotorConTranscripcionFalsa())
    job_id = upload(client, clip_5s).json()["job_id"]  # palabras "hola" 0-0.5 s y "mundo" 0.5-1.0 s
    wait_for(client, job_id, "ready")
    video = client.app.state.jobs.job_dir(job_id) / "input.mp4"
    sin = tmp_path / "sin.jpg"

    pedido = client.get(f"/api/jobs/{job_id}/preview-frame", params={"preset": "ken_classic", "t": 0.25})
    assert pedido.status_code == 200
    (tmp_path / "pedido.jpg").write_bytes(pedido.content)
    thumbs.render_frame(video, None, 0.25, 360, sin)
    assert changed_pixels(tmp_path / "pedido.jpg", sin) > 100  # dentro de "hola": se ve el subtítulo

    automatico = client.get(f"/api/jobs/{job_id}/preview-frame", params={"preset": "ken_classic"})
    instante = float(automatico.headers["x-frame-time"])
    (tmp_path / "auto.jpg").write_bytes(automatico.content)
    thumbs.render_frame(video, None, instante, 360, sin)
    assert changed_pixels(tmp_path / "auto.jpg", sin) > 100  # el instante automático también lo muestra

    fuera = client.get(f"/api/jobs/{job_id}/preview-frame", params={"preset": "ken_classic", "t": 4.5})
    (tmp_path / "fuera.jpg").write_bytes(fuera.content)
    thumbs.render_frame(video, None, 4.5, 360, sin)
    assert changed_pixels(tmp_path / "fuera.jpg", sin) <= 20  # a 4.5 s no hay palabras


GANCHO = {"headline": "Hola gancho", "duration_s": 2}


def _descargar(client, url, destino):
    destino.write_bytes(client.get(url).content)
    return destino


def _fotograma(video, at, destino):
    from engine.ffbin import ffmpeg_bin

    subprocess.run(
        [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-ss", f"{at:g}", "-i", str(video),
         "-frames:v", "1", "-y", str(destino)],
        check=True,
    )
    return destino


@requires_libass
def test_render_con_gancho_pinta_la_pastilla_solo_mientras_dura(start_app, clip_5s, tmp_path):
    client, _ = start_app(engine=MotorConTranscripcionFalsa())
    job_id = upload(client, clip_5s).json()["job_id"]
    wait_for(client, job_id, "ready")

    assert client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": 3, "hook": GANCHO}).status_code == 202
    con = _descargar(client, wait_for(client, job_id, "done")["urls"]["preview"], tmp_path / "con.mp4")
    assert client.put(f"/api/jobs/{job_id}/hook", content="null", headers={"content-type": "application/json"}).status_code == 200  # sin gancho guardado
    assert client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": 3}).status_code == 202
    sin = _descargar(client, wait_for(client, job_id, "done")["urls"]["preview"], tmp_path / "sin.mp4")

    con_1, sin_1 = _fotograma(con, 1.0, tmp_path / "con-1.png"), _fotograma(sin, 1.0, tmp_path / "sin-1.png")
    assert changed_pixels(con_1, sin_1) > 1000  # a 1 s la pastilla está en pantalla
    con_2, sin_2 = _fotograma(con, 2.5, tmp_path / "con-2.png"), _fotograma(sin, 2.5, tmp_path / "sin-2.png")
    assert changed_pixels(con_2, sin_2) <= 20  # a 2.5 s el gancho, de 2 s, ya no está


@requires_libass
def test_render_completo_con_gancho_mantiene_la_duracion_y_la_pastilla(start_app, clip_5s, tmp_path):
    client, _ = start_app(engine=MotorConTranscripcionFalsa())
    job_id = upload(client, clip_5s).json()["job_id"]
    wait_for(client, job_id, "ready")

    assert client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": None, "hook": GANCHO}).status_code == 202
    con = _descargar(client, wait_for(client, job_id, "done")["urls"]["output"], tmp_path / "con.mp4")
    assert 4.8 <= _probe(con)["duration"] <= 5.3
    assert client.put(f"/api/jobs/{job_id}/hook", content="null", headers={"content-type": "application/json"}).status_code == 200
    assert client.post(f"/api/jobs/{job_id}/render", json={"preview_seconds": None}).status_code == 202
    sin = _descargar(client, wait_for(client, job_id, "done")["urls"]["output"], tmp_path / "sin.mp4")

    con_1, sin_1 = _fotograma(con, 1.0, tmp_path / "con-1.png"), _fotograma(sin, 1.0, tmp_path / "sin-1.png")
    assert changed_pixels(con_1, sin_1) > 1000  # el MP4 final lleva la pastilla a 1 s
    con_2, sin_2 = _fotograma(con, 2.5, tmp_path / "con-2.png"), _fotograma(sin, 2.5, tmp_path / "sin-2.png")
    assert changed_pixels(con_2, sin_2) <= 20  # y ya no la lleva a 2.5 s
