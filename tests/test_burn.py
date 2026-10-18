import subprocess
import tempfile
from pathlib import Path

import pytest

from engine import burn
from engine.ffbin import ffmpeg_bin
from engine.textmetrics import FONTS_DIR

LISTING_TWO_FLAGS = " .. ass               V->V       Render ASS subtitles onto input video using the libass library.\n"
LISTING_THREE_FLAGS = " T.. ass               V->V       Render ASS subtitles onto input video using the libass library.\n"
LISTING_SUBTITLES_ONLY = " .. subtitles         V->V       Render text subtitles onto input video using the libass library.\n"
HELP_WITH_ASS = "Filter ass\n  Render ASS subtitles onto input video using the libass library.\n"
HELP_WITHOUT_ASS = "Unknown filter 'ass'.\n"


@pytest.fixture(autouse=True)
def fresh_cache():
    burn.is_available.cache_clear()
    yield
    burn.is_available.cache_clear()


def test_listing_format_accepts_two_or_three_flag_characters():
    assert burn._has_ass_filter("Filters:\n" + LISTING_TWO_FLAGS)
    assert burn._has_ass_filter("Filters:\n" + LISTING_THREE_FLAGS)


def test_listing_format_ignores_the_subtitles_filter():
    assert not burn._has_ass_filter(LISTING_SUBTITLES_ONLY)


def test_help_format_needs_exit_zero_and_the_filter_header():
    assert burn._ass_help_ok(0, HELP_WITH_ASS)


def test_help_format_is_not_available_with_exit_zero_when_the_filter_is_unknown():
    assert not burn._ass_help_ok(0, HELP_WITHOUT_ASS)


def test_help_format_is_not_available_with_a_nonzero_exit():
    assert not burn._ass_help_ok(1, HELP_WITH_ASS)


def test_is_available_matches_the_resolved_ffmpeg():
    result = subprocess.run([ffmpeg_bin(), "-hide_banner", "-h", "filter=ass"], capture_output=True, text=True)
    assert burn.is_available() is burn._ass_help_ok(result.returncode, result.stdout)


def test_is_available_is_cached_after_the_first_call(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=HELP_WITH_ASS, stderr="")

    monkeypatch.setattr(burn.subprocess, "run", fake_run)
    assert burn.is_available() is True
    assert burn.is_available() is True
    assert len(calls) == 1


def test_is_available_is_false_for_exit_zero_without_the_filter(monkeypatch):
    monkeypatch.setattr(
        burn.subprocess, "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, stdout=HELP_WITHOUT_ASS, stderr=""),
    )
    assert burn.is_available() is False


def test_is_available_is_false_when_ffmpeg_is_missing(monkeypatch):
    def missing(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(burn.subprocess, "run", missing)
    assert burn.is_available() is False


def test_burn_refuses_to_run_without_libass(monkeypatch, tmp_path):
    monkeypatch.setattr(burn, "is_available", lambda: False)
    with pytest.raises(RuntimeError, match="libass"):
        burn.burn(tmp_path / "in.mp4", "[Script Info]", tmp_path / "out.mp4", FONTS_DIR)


def test_fonts_for_burn_copies_only_static_fonts(tmp_path):
    source = tmp_path / "fonts"
    source.mkdir()
    for name in ["Static-Bold.ttf", "Variable[wght].ttf", "Other.otf", "OFL.txt"]:
        (source / name).write_bytes(b"font")
    dest = tmp_path / "job" / "fonts"
    copied = burn.fonts_for_burn(source, dest)
    assert sorted(path.name for path in copied) == ["Other.otf", "Static-Bold.ttf"]
    assert sorted(path.name for path in dest.iterdir()) == ["Other.otf", "Static-Bold.ttf"]


def test_fonts_for_burn_on_project_fonts_leaves_out_the_variable_font(tmp_path):
    names = {path.name for path in burn.fonts_for_burn(FONTS_DIR, tmp_path / "fonts")}
    assert "Montserrat[wght].ttf" not in names
    assert {"Montserrat-Bold.ttf", "Montserrat-ExtraBold.ttf", "Anton-Regular.ttf",
            "InstrumentSerif-Italic.ttf"} <= names


def test_final_render_command_uses_the_agreed_flags():
    cmd = burn._command(Path("/a/in.mp4"), Path("/b/out.mp4"), None)
    assert cmd[cmd.index("-preset") + 1] == "medium"
    assert cmd[cmd.index("-crf") + 1] == "18"
    assert "-t" not in cmd
    assert cmd[cmd.index("-vf") + 1] == "ass=subtitles.ass:fontsdir=fonts"
    assert cmd[cmd.index("-progress") + 1] == "pipe:1"
    assert "-nostats" in cmd
    assert cmd[cmd.index("-movflags") + 1] == "+faststart"
    assert cmd[-1] == "/b/out.mp4"


def test_preview_command_trims_and_uses_the_fast_preset():
    cmd = burn._command(Path("/a/in.mp4"), Path("/b/out.mp4"), 3)
    assert cmd[cmd.index("-t") + 1] == "3"
    assert cmd[cmd.index("-preset") + 1] == "veryfast"
    assert cmd[cmd.index("-crf") + 1] == "23"


def test_progress_seconds_reads_out_time_us_only():
    assert burn._progress_seconds("out_time_us=1500000\n") == 1.5
    assert burn._progress_seconds("out_time_us=N/A\n") is None
    assert burn._progress_seconds("progress=end\n") is None


def test_error_tail_keeps_the_last_40_lines():
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
        errors.write("".join(f"linea {i}\n" for i in range(50)))
        lines = burn._tail(errors).splitlines()
    assert len(lines) == 40
    assert lines[0] == "linea 10"
    assert lines[-1] == "linea 49"
