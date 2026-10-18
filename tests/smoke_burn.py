"""Smoke de quemado real con libass: presets sobre un video vertical de prueba. No forma parte de pytest.

Uso: .venv/bin/python tests/smoke_burn.py [--size 1080x1920] [--preview] [preset ...]
Escribe tests/fixtures/sample_<size>.mp4, tests/out/jobs/<preset>/ y tests/out/frames/<preset>_<t>.png.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.ffbin import ffmpeg_bin, ffprobe_bin  # noqa: E402
from engine.pipeline import run_job  # noqa: E402
from engine.styles import list_presets  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
OUT = ROOT / "tests" / "out"
FRAME_TIMES = (0.5, 1.5, 3.0)


def ffmpeg(*args):
    subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def make_video(path, size):
    ffmpeg(
        "-f", "lavfi", "-i", f"color=c=0x1d3b2f:s={size}:r=30",
        "-i", str(FIXTURES / "sample.aiff"),
        "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(path),
    )


def probe(path):
    out = subprocess.run(
        [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    audio = [s for s in data["streams"] if s["codec_type"] == "audio"]
    return {"w": video["width"], "h": video["height"], "duration": float(data["format"]["duration"]),
            "audio": bool(audio)}


def grab_frame(video, seconds, path):
    ffmpeg("-i", str(video), "-ss", f"{seconds}", "-frames:v", "1", str(path))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("presets", nargs="*")
    parser.add_argument("--size", default="1080x1920")
    parser.add_argument("--preview", action="store_true", help="cronometra además un preview de 3 s")
    args = parser.parse_args()
    presets = args.presets or [preset["name"] for preset in list_presets()]

    FIXTURES.mkdir(parents=True, exist_ok=True)
    frames = OUT / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    video = FIXTURES / f"sample_{args.size}.mp4"
    if not video.exists():
        make_video(video, args.size)
    src = probe(video)
    print(f"input {args.size}: {src['w']}x{src['h']} dur {src['duration']:.2f}s audio {src['audio']} "
          f"size {video.stat().st_size} bytes")

    for name in presets:
        start = time.perf_counter()
        result = run_job(video, OUT / "jobs" / name, preset=name, burn=True)
        elapsed = time.perf_counter() - start
        out = probe(result["output_path"])
        for seconds in FRAME_TIMES:
            grab_frame(result["output_path"], seconds, frames / f"{name}_{args.size}_{seconds:.1f}.png")
        print(f"{name}: {elapsed:.1f}s | {out['w']}x{out['h']} | dur {out['duration']:.2f}s | audio {out['audio']}")

    if args.preview:
        name = presets[0]
        start = time.perf_counter()
        result = run_job(video, OUT / "jobs" / f"preview_{name}", preset=name, burn=True, preview_seconds=3)
        elapsed = time.perf_counter() - start
        out = probe(result["output_path"])
        print(f"preview {name} (3 s): {elapsed:.1f}s | {out['w']}x{out['h']} | dur {out['duration']:.2f}s "
              f"| audio {out['audio']}")


if __name__ == "__main__":
    main()
