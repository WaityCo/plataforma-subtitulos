from pathlib import Path

import pytest

from engine import burn


@pytest.fixture(autouse=True)
def no_videotoolbox_by_default(monkeypatch):
    monkeypatch.delenv("SUBS_VIDEO_ENCODER", raising=False)
    monkeypatch.setattr(burn, "_has_videotoolbox", lambda: False)  # cada prueba activa VideoToolbox si lo necesita


def on_mac_with_videotoolbox(monkeypatch):
    monkeypatch.setattr(burn.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(burn, "_has_videotoolbox", lambda: True)


def value_after(args, flag):
    return args[args.index(flag) + 1]


def test_default_encoder_is_auto():
    assert burn.configured_encoder() == "auto"


def test_invalid_encoder_names_the_variable(monkeypatch):
    monkeypatch.setenv("SUBS_VIDEO_ENCODER", "nvenc")
    with pytest.raises(ValueError, match="SUBS_VIDEO_ENCODER"):
        burn.configured_encoder()


def test_auto_on_mac_uses_videotoolbox_at_6_mbps(monkeypatch):
    on_mac_with_videotoolbox(monkeypatch)
    args = burn.video_args(1080, 1920, preview=False)
    assert value_after(args, "-c:v") == "h264_videotoolbox"
    assert value_after(args, "-b:v") == "6000k"


def test_previews_on_mac_use_a_lower_bitrate(monkeypatch):
    on_mac_with_videotoolbox(monkeypatch)
    assert value_after(burn.video_args(1080, 1920, preview=True), "-b:v") == "3000k"


def test_bitrate_scales_by_area(monkeypatch):
    on_mac_with_videotoolbox(monkeypatch)
    # 720x1280 tiene 4/9 del área de 1080x1920: 6000 * 720 * 1280 / (1080 * 1920) = 2667
    assert value_after(burn.video_args(720, 1280, preview=False), "-b:v") == "2667k"


def test_auto_without_mac_uses_libx264_veryfast_crf20(monkeypatch):
    monkeypatch.setattr(burn.platform, "system", lambda: "Linux")
    args = burn.video_args(1080, 1920, preview=False)
    assert value_after(args, "-c:v") == "libx264"
    assert value_after(args, "-preset") == "veryfast"
    assert value_after(args, "-crf") == "20"


def test_auto_on_mac_without_videotoolbox_falls_back_to_libx264(monkeypatch):
    monkeypatch.setattr(burn.platform, "system", lambda: "Darwin")
    assert value_after(burn.video_args(1080, 1920, preview=False), "-c:v") == "libx264"


def test_explicit_libx264_keeps_the_reference_settings(monkeypatch):
    on_mac_with_videotoolbox(monkeypatch)
    monkeypatch.setenv("SUBS_VIDEO_ENCODER", "libx264")
    args = burn.video_args(1080, 1920, preview=False)
    assert value_after(args, "-preset") == "medium"
    assert value_after(args, "-crf") == "18"


def test_explicit_videotoolbox_without_the_encoder_fails(monkeypatch):
    monkeypatch.setenv("SUBS_VIDEO_ENCODER", "videotoolbox")
    with pytest.raises(RuntimeError, match="h264_videotoolbox"):
        burn.video_args(1080, 1920, preview=False)


def test_audio_is_copied_when_it_is_aac(monkeypatch, tmp_path):
    monkeypatch.setattr(burn, "audio_codec", lambda path: "aac")
    assert burn.audio_args(tmp_path / "in.mp4") == ["-c:a", "copy"]


def test_audio_is_encoded_to_aac_192k_otherwise(monkeypatch, tmp_path):
    monkeypatch.setattr(burn, "audio_codec", lambda path: "opus")
    assert burn.audio_args(tmp_path / "in.mp4") == ["-c:a", "aac", "-b:a", "192k"]
    monkeypatch.setattr(burn, "audio_codec", lambda path: None)
    assert burn.audio_args(tmp_path / "in.mp4") == ["-c:a", "aac", "-b:a", "192k"]


def test_command_adds_threads_and_uses_the_given_codecs():
    video = ["-c:v", "h264_videotoolbox", "-b:v", "6000k"]
    cmd = burn._command(Path("/a/in.mp4"), Path("/b/out.mp4"), None, video=video, audio=["-c:a", "copy"])
    assert value_after(cmd, "-c:v") == "h264_videotoolbox"
    assert value_after(cmd, "-threads") == "0"
    assert value_after(cmd, "-c:a") == "copy"
    assert cmd[-1] == "/b/out.mp4"
