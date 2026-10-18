"""Mensajes 409: el estado del job va en español y sin nombres internos (B10)."""

import uuid

import pytest

from backend.config import Settings
from backend.jobs import JobConflict, JobManager
from backend.tests.fakes import FakeEngine
from backend.tests.helpers import job_row

ESTADOS = [
    ("queued", "en cola"),
    ("transcribing", "transcribiendo"),
    ("ready", "listo"),
    ("rendering", "renderizando"),
    ("done", "terminado"),
    ("error", "error"),
]


def _manager(tmp_path, *, burn_ok=False):
    engine = FakeEngine()
    engine.burn_ok = burn_ok
    manager = JobManager(Settings(data_dir=tmp_path), engine)
    manager.store.init()
    return manager


@pytest.mark.parametrize("status, legible", ESTADOS)
def test_409_de_palabras_dice_el_estado_en_espanol(tmp_path, status, legible):
    manager = _manager(tmp_path)
    job = uuid.uuid4().hex
    manager.store.create(job_row(job, status))  # sin words.json: ningún estado es editable

    with pytest.raises(JobConflict) as error:
        manager.update_words(job, [{"text": "x", "start": 0, "end": 1}])

    assert str(error.value) == f"El job no admite este cambio en estado '{legible}'."


@pytest.mark.parametrize("status, legible", ESTADOS)
def test_409_de_segmentos_dice_el_estado_en_espanol(tmp_path, status, legible):
    manager = _manager(tmp_path)
    job = uuid.uuid4().hex
    manager.store.create(job_row(job, status))

    with pytest.raises(JobConflict) as error:
        manager.segments(job)

    assert str(error.value) == f"El job todavía no tiene palabras (estado: '{legible}')."


@pytest.mark.parametrize("status, legible", [estado for estado in ESTADOS if estado[0] not in ("ready", "done")])
def test_409_de_miniaturas_dice_el_estado_en_espanol(tmp_path, status, legible):
    manager = _manager(tmp_path, burn_ok=True)
    job = uuid.uuid4().hex
    manager.store.create(job_row(job, status))

    with pytest.raises(JobConflict) as error:
        manager.preview_frame(job, None, None, None, 360)

    assert str(error.value) == f"El job no está listo para miniaturas (estado: '{legible}')."


def test_render_sin_subtitulos_dice_que_faltan_los_subtitulos(tmp_path):
    manager = _manager(tmp_path, burn_ok=True)
    job = uuid.uuid4().hex
    manager.store.create(job_row(job, "ready"))
    manager.job_dir(job).mkdir(parents=True)
    (manager.job_dir(job) / "words.json").write_text("[]", encoding="utf-8")  # hay palabras, pero no ASS

    with pytest.raises(JobConflict) as error:
        manager.request_render(job, None)

    assert str(error.value) == "Faltan los subtítulos del job: no hay nada que quemar."
