"""Fixtures: video real generado con ffmpeg lavfi y arranque de la API con motor falso."""

import contextlib
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.tests.fakes import FakeEngine


@pytest.fixture(scope="session")
def sample_videos(tmp_path_factory) -> dict[str, Path]:
    """Videos de 2 s (720x1280) generados con ffmpeg lavfi: mp4, mov y webm."""
    folder = tmp_path_factory.mktemp("videos")
    codecs = {
        "sample.mp4": ["-c:v", "libx264", "-pix_fmt", "yuv420p"],
        "sample.mov": ["-c:v", "libx264", "-pix_fmt", "yuv420p"],
        "sample.webm": ["-c:v", "libvpx", "-b:v", "300k"],
    }
    paths = {}
    for name, codec in codecs.items():
        target = folder / name
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=duration=2:size=720x1280:rate=25",
                *codec, "-y", str(target),
            ],
            check=True,
        )
        paths[name] = target
    return paths


@pytest.fixture
def start_app(tmp_path):
    """Levanta la API con su ciclo de vida (worker incluido) sobre una carpeta temporal."""
    stack = contextlib.ExitStack()
    engines: list = []

    def _start(
        *, engine=None, max_upload_bytes=None, chunk_bytes=None, data_dir=None, frontend_dir=None, presets_dir=None
    ):
        engine = FakeEngine() if engine is None else engine
        engines.append(engine)
        settings = Settings(data_dir=data_dir or tmp_path / "data")
        if max_upload_bytes is not None:
            settings = replace(settings, max_upload_bytes=max_upload_bytes)
        if chunk_bytes is not None:
            settings = replace(settings, chunk_bytes=chunk_bytes)
        app = create_app(settings=settings, engine=engine, frontend_dir=frontend_dir, presets_dir=presets_dir)
        client = stack.enter_context(TestClient(app))
        return client, engine

    yield _start
    for engine in engines:  # libera transcripciones y quemados bloqueados para que el worker pueda parar
        if isinstance(engine, FakeEngine):
            engine.gate.set()
            engine.burn_gate.set()
    stack.close()
