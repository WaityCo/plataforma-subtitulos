"""Miniaturas: puntuación y tiempo automático, clave de caché, semáforo, tamaño y el subtítulo en su instante."""

import struct
import subprocess
import threading
import time
from pathlib import Path

import pytest

from backend import thumbs
from backend.tests.motor_real import REAL, changed_pixels, make_clip, requires_libass

PHRASE = {"mode": "phrase", "box_color": None}
KARAOKE = {"mode": "karaoke", "box_color": None}


def _w(text, start, end, index, emph=False):
    return {"text": text, "display": text, "start": start, "end": end, "emph": emph, "index": index}


def _seg(*words, windows=None):
    return {"start": words[0]["start"], "end": words[-1]["end"], "lines": [list(words)], "windows": windows or [], "fit": 100}


def _jpeg_size(path):
    data = Path(path).read_bytes()
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        if data[i + 1] in (0xC0, 0xC1, 0xC2):
            height, width = struct.unpack(">HH", data[i + 5:i + 9])
            return width, height
        i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    raise ValueError("JPEG sin cabecera de tamaño")


def test_score_suma_caracteres_palabras_enfasis_y_palabra_activa():
    frase = _seg(
        _w("consejo", 0.0, 0.5, 0, emph=True),
        _w("sencillo", 0.5, 1.0, 1),
        windows=[{"index": 0, "start": 0.0, "end": 0.5}],
    )

    assert thumbs.score(frase) == 16 + 10 + 8 + 6  # "consejo sencillo" tiene 16 caracteres


def test_score_penaliza_la_palabra_suelta():
    assert thumbs.score(_seg(_w("25.", 0.0, 0.5, 0))) == 3 - 15


def test_score_topa_los_caracteres_en_24():
    frase = _seg(*[_w(palabra, i, i + 1, i) for i, palabra in enumerate("uno dos tres cuatro cinco seis siete".split())])

    assert thumbs.score(frase) == 24 + 10  # 36 caracteres, contados hasta 24


def test_pick_time_mira_solo_el_primer_60_por_ciento():
    dentro = _seg(_w("dentro", 5.5, 6.0, 0), _w("sencillo", 6.0, 6.5, 1))  # empieza al 55 %
    fuera = _seg(_w("fuera", 6.5, 7.0, 2), _w("alta", 7.0, 7.5, 3), _w("puntuacion", 7.5, 8.0, 4, emph=True))

    assert thumbs.pick_time([dentro, fuera], duration=10.0, style=PHRASE) == pytest.approx(6.0)


def test_pick_time_descarta_las_palabras_sueltas():
    suelta = _seg(_w("25.", 0.5, 1.0, 0))
    frase = _seg(_w("consejo", 2.0, 2.4, 1), _w("sencillo", 2.4, 2.8, 2))

    assert thumbs.pick_time([suelta, frase], duration=10.0, style=PHRASE) == pytest.approx(2.4)


def test_pick_time_en_empate_gana_el_primero_aunque_llegue_despues():
    primero = _seg(_w("uno", 1.0, 1.5, 0), _w("dos", 1.5, 2.0, 1))
    despues = _seg(_w("uno", 3.0, 3.5, 2), _w("dos", 3.5, 4.0, 3))

    assert thumbs.pick_time([despues, primero], duration=10.0, style=PHRASE) == pytest.approx(1.5)


def test_pick_time_sin_candidatos_en_la_zona_usa_todos_los_segmentos():
    lejos = _seg(_w("final", 7.0, 7.5, 0), _w("largo", 7.5, 8.0, 1), _w("texto", 8.0, 8.5, 2, emph=True))

    assert thumbs.pick_time([lejos], duration=10.0, style=PHRASE) == pytest.approx((7.0 + 8.5) / 2)


def test_pick_time_sin_segmentos_usa_la_mitad_del_video():
    assert thumbs.pick_time([], duration=8.0, style=PHRASE) == pytest.approx(4.0)


def test_phrase_usa_el_centro_de_la_frase():
    frase = _seg(_w("a", 1.0, 2.0, 0), _w("b", 2.0, 3.0, 1))

    assert thumbs.instant_for(frase, PHRASE) == pytest.approx(2.0)


def test_karaoke_usa_la_tercera_palabra_activa():
    frase = _seg(
        _w("a", 0.0, 0.5, 0),
        _w("b", 0.5, 1.0, 1),
        _w("c", 1.0, 1.5, 2),
        windows=[{"index": 2, "start": 1.1, "end": 1.4}],
    )

    assert thumbs.instant_for(frase, KARAOKE) == pytest.approx(1.25)


def test_karaoke_sin_ventanas_usa_el_tiempo_de_la_palabra():
    frase = _seg(_w("a", 0.0, 0.5, 0), _w("b", 0.5, 1.0, 1), _w("c", 1.0, 1.6, 2))

    assert thumbs.instant_for(frase, KARAOKE) == pytest.approx(1.3)


def test_karaoke_con_dos_palabras_usa_la_segunda():
    frase = _seg(_w("a", 0.0, 0.5, 0), _w("b", 0.5, 1.0, 1), windows=[{"index": 1, "start": 0.6, "end": 0.9}])

    assert thumbs.instant_for(frase, KARAOKE) == pytest.approx(0.75)


def test_karaoke_con_una_palabra_usa_el_centro_del_segmento():
    assert thumbs.instant_for(_seg(_w("sola", 0.0, 1.0, 0)), KARAOKE) == pytest.approx(0.5)


@pytest.mark.parametrize("mode", ["karaoke", "karaoke_sweep", "karaoke_box", "reveal"])
def test_modos_de_palabras_comparten_el_criterio_de_la_tercera(mode):
    frase = _seg(
        _w("a", 0.0, 0.5, 0),
        _w("b", 0.5, 1.0, 1),
        _w("c", 1.0, 1.5, 2),
        windows=[{"index": 2, "start": 1.1, "end": 1.4}],
    )

    assert thumbs.instant_for(frase, {"mode": mode}) == pytest.approx(1.25)


def test_clamp_time_no_pasa_del_final_ni_va_negativo():
    assert thumbs.clamp_time(-1.0, 5.0) == 0.0
    assert thumbs.clamp_time(9.0, 5.0) == pytest.approx(4.96)


def test_cache_key_cambia_con_cada_entrada():
    base = dict(job_id="a" * 32, preset="ken_classic", overrides=None, time=1.5, width=360, ass_text="x")
    clave = thumbs.cache_key(**base)

    assert clave == thumbs.cache_key(**base)
    for cambio in (
        {"preset": "phrase_box"},
        {"overrides": {"font_size": 70}},
        {"time": 1.6},
        {"width": 720},
        {"ass_text": "y"},
        {"job_id": "b" * 32},
    ):
        assert thumbs.cache_key(**{**base, **cambio}) != clave


def test_invalidate_quita_las_miniaturas(tmp_path):
    (tmp_path / thumbs.THUMBS_DIR).mkdir()
    (tmp_path / thumbs.THUMBS_DIR / "x.jpg").write_bytes(b"x")

    thumbs.invalidate(tmp_path)

    assert not (tmp_path / thumbs.THUMBS_DIR).exists()


def test_semaforo_deja_correr_dos_ffmpeg_a_la_vez(monkeypatch, tmp_path):
    activos, maximo, cerrojo = 0, 0, threading.Lock()

    def fake_run(command, cwd, capture_output, text):
        nonlocal activos, maximo
        with cerrojo:
            activos += 1
            maximo = max(maximo, activos)
        time.sleep(0.15)
        Path(command[-1]).write_bytes(b"\xff\xd8\xff")
        with cerrojo:
            activos -= 1
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(thumbs.subprocess, "run", fake_run)
    hilos = [
        threading.Thread(target=thumbs.render_frame, args=(tmp_path / "x.mp4", None, 1.0, 360, tmp_path / f"{i}.jpg"))
        for i in range(6)
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    assert maximo == 2


def test_ancho_respeta_w_y_no_agranda(tmp_path):
    clip = make_clip(tmp_path, seconds=1)

    thumbs.render_frame(clip, None, 0.5, 360, tmp_path / "a.jpg")
    thumbs.render_frame(clip, None, 0.5, 1080, tmp_path / "b.jpg")

    assert _jpeg_size(tmp_path / "a.jpg")[0] == 360
    assert _jpeg_size(tmp_path / "b.jpg")[0] == 720  # el video mide 720: no se agranda


@requires_libass
def test_fotograma_muestra_el_subtitulo_en_su_instante_y_no_fuera_de_el(tmp_path):
    clip = make_clip(tmp_path, seconds=5)
    style = REAL.resolve_style("ken_classic", None)
    ass = REAL.build_ass([{"text": "HOLA MUNDO", "start": 1.0, "end": 2.0}], style, 720, 1280)
    con, sin = tmp_path / "con.jpg", tmp_path / "sin.jpg"

    thumbs.render_frame(clip, ass, 1.5, 360, con)
    thumbs.render_frame(clip, None, 1.5, 360, sin)
    assert changed_pixels(con, sin) > 100  # a 1.5 s el subtítulo está en pantalla

    thumbs.render_frame(clip, ass, 3.5, 360, con)
    thumbs.render_frame(clip, None, 3.5, 360, sin)
    assert changed_pixels(con, sin) <= 20  # a 3.5 s no hay subtítulo


def test_instante_fuera_del_video_no_tiene_fotograma(tmp_path):
    clip = make_clip(tmp_path, seconds=1)

    with pytest.raises(thumbs.InvalidFrame, match="No hay fotograma"):
        thumbs.render_frame(clip, None, 5.0, 360, tmp_path / "fuera.jpg")

    assert not (tmp_path / "fuera.jpg").exists()


def test_archivo_roto_es_frame_error_y_no_deja_restos(tmp_path):
    roto = tmp_path / "roto.mp4"
    roto.write_bytes(b"esto no es un video" * 200)

    with pytest.raises(thumbs.FrameError, match="ffmpeg no pudo sacar el fotograma"):
        thumbs.render_frame(roto, None, 0.5, 360, tmp_path / "roto.jpg")

    assert not (tmp_path / "roto.jpg").exists()
    assert not (tmp_path / "roto.jpg.part").exists()


def test_ffmpeg_que_no_arranca_es_frame_error(monkeypatch, tmp_path):
    def sin_ejecutable(*args, **kwargs):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(thumbs.subprocess, "run", sin_ejecutable)

    with pytest.raises(thumbs.FrameError, match="No se pudo ejecutar ffmpeg"):
        thumbs.render_frame(tmp_path / "x.mp4", None, 0.5, 360, tmp_path / "x.jpg")


def test_auto_t_con_gancho_elige_un_segmento_que_empieza_despues_del_gancho():
    antes = _seg(_w("consejo", 0.5, 0.9, 0), _w("sencillo", 0.9, 1.3, 1))  # frase: puntúa más
    tras = _seg(_w("tras", 2.5, 3.0, 2))  # palabra suelta después de un gancho de 2 s

    assert thumbs.pick_time([antes, tras], duration=10.0, style=PHRASE, hook_end=2.0) == pytest.approx(2.75)


def test_auto_t_con_gancho_usa_su_tramo_si_no_hay_nada_despues():
    antes = _seg(_w("consejo", 0.5, 0.9, 0), _w("sencillo", 0.9, 1.3, 1))
    otra = _seg(_w("uno", 1.5, 1.8, 2))

    assert thumbs.pick_time([antes, otra], duration=10.0, style=PHRASE, hook_end=2.0) == pytest.approx(0.9)


def test_auto_t_sin_gancho_no_cambia_el_criterio():
    antes = _seg(_w("consejo", 0.5, 0.9, 0), _w("sencillo", 0.9, 1.3, 1))
    tras = _seg(_w("tras", 2.5, 3.0, 2))

    assert thumbs.pick_time([antes, tras], duration=10.0, style=PHRASE) == pytest.approx(0.9)
