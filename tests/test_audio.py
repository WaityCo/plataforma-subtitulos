import json
import subprocess

import pytest

from engine import audio


def completed(cmd, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)


def test_extract_audio_builds_mono_16k_command(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return completed(cmd)

    monkeypatch.setattr(audio.subprocess, "run", fake_run)
    audio.extract_audio(tmp_path / "in.mp4", tmp_path / "audio.wav")
    cmd = seen["cmd"]
    assert "-vn" in cmd
    assert cmd[cmd.index("-ac") + 1] == "1"
    assert cmd[cmd.index("-ar") + 1] == "16000"


def test_extract_audio_raises_runtime_error_with_ffmpeg_stderr(monkeypatch, tmp_path):
    monkeypatch.setattr(
        audio.subprocess, "run",
        lambda cmd, **kwargs: completed(cmd, returncode=1, stderr="Invalid data found"),
    )
    with pytest.raises(RuntimeError, match="Invalid data found"):
        audio.extract_audio(tmp_path / "in.mp4", tmp_path / "audio.wav")


def test_probe_swaps_size_for_rotated_phone_video(monkeypatch):
    payload = {
        "streams": [{"codec_type": "video", "width": 1920, "height": 1080, "side_data_list": [{"rotation": -90}]}],
        "format": {"duration": "12.5"},
    }
    monkeypatch.setattr(audio.subprocess, "run", lambda cmd, **kwargs: completed(cmd, stdout=json.dumps(payload)))
    assert audio.probe_video("in.mp4") == {"width": 1080, "height": 1920, "duration": 12.5}


def test_probe_without_video_stream_raises(monkeypatch):
    payload = {"streams": [{"codec_type": "audio"}], "format": {"duration": "3"}}
    monkeypatch.setattr(audio.subprocess, "run", lambda cmd, **kwargs: completed(cmd, stdout=json.dumps(payload)))
    with pytest.raises(RuntimeError, match="stream de video"):
        audio.probe_video("in.mp4")
