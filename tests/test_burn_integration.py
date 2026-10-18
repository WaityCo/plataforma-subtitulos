import json
import subprocess

import pytest

from engine.ass_builder import build_ass
from engine.burn import burn, is_available
from engine.ffbin import ffmpeg_bin, ffprobe_bin
from engine.styles import resolve
from engine.textmetrics import FONTS_DIR

pytestmark = pytest.mark.skipif(not is_available(), reason="el ffmpeg resuelto no tiene libass")


def probe(path):
    out = subprocess.run(
        [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def test_two_second_burn_keeps_size_duration_and_audio(tmp_path):
    source = tmp_path / "source.mp4"
    subprocess.run(
        [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=0x1d3b2f:s=360x640:d=2",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)],
        check=True,
    )
    ass = build_ass([{"text": "Hola", "start": 0.2, "end": 1.2}], resolve("minimal_mono"), 360, 640)
    output = tmp_path / "out.mp4"
    burn(source, ass, output, FONTS_DIR)
    data = probe(output)
    video = next(stream for stream in data["streams"] if stream["codec_type"] == "video")
    assert (video["width"], video["height"]) == (360, 640)
    assert any(stream["codec_type"] == "audio" for stream in data["streams"])
    assert abs(float(data["format"]["duration"]) - 2.0) < 0.2
