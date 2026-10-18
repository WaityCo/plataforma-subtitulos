"""Video sin pista de audio: has_audio lo detecta y el job termina con words.json vacío (F21)."""

import json
import subprocess
from pathlib import Path

from engine import audio, pipeline
from engine.ffbin import ffmpeg_bin

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample_720x1280.mp4"


def silent_video(path):
    subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=black:s=320x568:d=1", "-c:v", "libx264", "-an", str(path)], check=True)
    return path


def test_has_audio_sees_the_sound_track_of_a_sample_video():
    assert audio.has_audio(SAMPLE) is True


def test_has_audio_is_false_for_a_video_without_audio(tmp_path):
    assert audio.has_audio(silent_video(tmp_path / "mudo.mp4")) is False


def test_a_video_without_audio_finishes_with_empty_words_and_no_subtitles(tmp_path, monkeypatch):
    video = silent_video(tmp_path / "mudo.mp4")

    def must_not_run(*args, **kwargs):
        raise AssertionError("no debía transcribir un video sin audio")

    monkeypatch.setattr(pipeline, "transcribe", must_not_run)
    stages = []
    result = pipeline.run_job(video, tmp_path / "job", progress=lambda stage, percent: stages.append(stage))
    assert json.loads(Path(result["words_path"]).read_text(encoding="utf-8")) == []
    assert "Dialogue:" not in Path(result["ass_path"]).read_text(encoding="utf-8")
    assert result["output_path"] is None
    assert not (tmp_path / "job" / "audio.wav").exists()
    assert stages[-1] == "subtitles"
