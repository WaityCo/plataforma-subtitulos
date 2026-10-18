from engine import ffbin


def make_tool(directory, name):
    directory.mkdir(parents=True, exist_ok=True)
    tool = directory / name
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    return tool


def test_environment_variables_win(monkeypatch):
    monkeypatch.setenv("FFMPEG_BIN", "/custom/ffmpeg")
    monkeypatch.setenv("FFPROBE_BIN", "/custom/ffprobe")
    assert ffbin.ffmpeg_bin() == "/custom/ffmpeg"
    assert ffbin.ffprobe_bin() == "/custom/ffprobe"


def test_homebrew_ffmpeg_full_is_used_when_present(monkeypatch, tmp_path):
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    monkeypatch.setattr(ffbin, "FULL_DIR", tmp_path)
    tool = make_tool(tmp_path, "ffmpeg")
    assert ffbin.ffmpeg_bin() == str(tool)


def test_path_is_the_fallback_without_homebrew(monkeypatch, tmp_path):
    monkeypatch.delenv("FFPROBE_BIN", raising=False)
    monkeypatch.setattr(ffbin, "FULL_DIR", tmp_path / "missing")
    tool = make_tool(tmp_path / "bin", "ffprobe")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    assert ffbin.ffprobe_bin() == str(tool)


def test_bare_name_when_nothing_is_found(monkeypatch, tmp_path):
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    monkeypatch.setattr(ffbin, "FULL_DIR", tmp_path / "missing")
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert ffbin.ffmpeg_bin() == "ffmpeg"
