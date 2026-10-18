import json
from pathlib import Path

import pytest

from engine import pipeline

WORDS = [
    {"text": "Dormir", "start": 0.0, "end": 0.4},
    {"text": "también.", "start": 0.4, "end": 0.9},
]


@pytest.fixture
def fake_media(monkeypatch, tmp_path):
    video = tmp_path / "in.mp4"
    video.write_bytes(b"no es un video real")
    monkeypatch.setattr(pipeline, "probe_video", lambda path: {"width": 1080, "height": 1920, "duration": 6.5})
    monkeypatch.setattr(pipeline, "extract_audio", lambda video_path, wav_path: None)
    monkeypatch.setattr(pipeline, "has_audio", lambda path: True)
    monkeypatch.setattr(
        pipeline, "transcribe",
        lambda wav_path, language=None, model_size="small": [dict(word) for word in WORDS],
    )
    return video


def test_run_job_writes_outputs_and_reports_stages_in_order(fake_media, tmp_path):
    stages = []
    result = pipeline.run_job(
        fake_media, tmp_path / "job", preset="minimal_mono",
        progress=lambda stage, percent: stages.append((stage, percent)),
    )
    assert set(result) == {"output_path", "words_path", "ass_path", "duration_seconds", "hook_warnings"}
    assert result["output_path"] is None
    assert result["duration_seconds"] == 6.5
    assert stages == [
        ("audio", 0.0), ("audio", 100.0),
        ("transcribe", 0.0), ("transcribe", 100.0),
        ("subtitles", 0.0), ("subtitles", 100.0),
    ]
    assert json.loads(Path(result["words_path"]).read_text(encoding="utf-8")) == WORDS
    ass_bytes = Path(result["ass_path"]).read_bytes()
    assert not ass_bytes.startswith(b"\xef\xbb\xbf")
    assert "PlayResX: 1080" in ass_bytes.decode("utf-8")


def test_burn_runs_last_and_returns_output_path(fake_media, monkeypatch, tmp_path):
    calls = []

    def fake_burn(video, ass_text, output, fonts_dir, preview_seconds=None, progress=None, overlays=()):
        calls.append({"output": Path(output), "preview": preview_seconds, "overlays": list(overlays)})
        progress("burn", 100.0)

    monkeypatch.setattr(pipeline, "is_available", lambda: True)
    monkeypatch.setattr(pipeline, "burn_video", fake_burn)
    stages = []
    result = pipeline.run_job(
        fake_media, tmp_path / "job", burn=True, preview_seconds=3,
        progress=lambda stage, percent: stages.append(stage),
    )
    assert Path(result["output_path"]).name == "output.mp4"
    assert calls[0]["output"].name == "output.mp4"
    assert calls[0]["preview"] == 3
    assert stages[-2:] == ["subtitles", "burn"]


def test_preview_keeps_the_full_ass_and_only_limits_the_burn(fake_media, monkeypatch, tmp_path):
    late = [{"text": "tarde", "start": 5.0, "end": 5.5}]
    monkeypatch.setattr(pipeline, "transcribe", lambda wav_path, language=None, model_size="small": late)
    monkeypatch.setattr(pipeline, "is_available", lambda: True)
    monkeypatch.setattr(pipeline, "burn_video", lambda *args, **kwargs: None)
    result = pipeline.run_job(fake_media, tmp_path / "job", burn=True, preview_seconds=3)
    assert "0:00:05.00" in Path(result["ass_path"]).read_text(encoding="utf-8")


def test_burn_without_libass_fails_before_transcribing(fake_media, monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "is_available", lambda: False)

    def must_not_run(*args, **kwargs):
        raise AssertionError("no debía transcribir")

    monkeypatch.setattr(pipeline, "transcribe", must_not_run)
    with pytest.raises(RuntimeError, match="libass"):
        pipeline.run_job(fake_media, tmp_path / "job", burn=True)


def test_unknown_preset_fails_before_touching_media(monkeypatch, tmp_path):
    def must_not_run(*args, **kwargs):
        raise AssertionError("no debía analizar el video")

    monkeypatch.setattr(pipeline, "probe_video", must_not_run)
    with pytest.raises(ValueError, match="Preset desconocido"):
        pipeline.run_job(tmp_path / "in.mp4", tmp_path / "job", preset="no_existe")


def test_run_job_defaults_to_ken_remedie():
    import inspect

    assert inspect.signature(pipeline.run_job).parameters["preset"].default == "ken_remedie"


def test_cli_defaults_to_ken_remedie(monkeypatch, tmp_path):
    from engine import cli

    seen = {}

    def fake_run_job(video, out_dir, **kwargs):
        seen["preset"] = kwargs["preset"]
        return {"output_path": None}

    monkeypatch.setattr(cli, "run_job", fake_run_job)
    video = tmp_path / "in.mp4"
    video.write_bytes(b"no es un video real")
    assert cli.main([str(video), "--out-dir", str(tmp_path / "job"), "--no-burn"]) == 0
    assert seen["preset"] == "ken_remedie"
