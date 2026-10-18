"""Smoke test manual de transcripción: say -> WAV 16 kHz -> transcribe.

No forma parte de pytest: necesita faster-whisper y descarga el modelo la primera vez.
Uso: .venv/bin/python tests/smoke_transcribe.py
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.transcribe import transcribe  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
OUT = ROOT / "tests" / "out"
TEXT = "Hola, hoy te comparto tres formas sencillas de dormir mejor."


def make_sample():
    FIXTURES.mkdir(parents=True, exist_ok=True)
    aiff = FIXTURES / "sample.aiff"
    for voice in ("Mónica", "Paulina"):
        result = subprocess.run(["say", "-v", voice, "-o", str(aiff), TEXT], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"voz: {voice}")
            break
        print(f"say falló con {voice}: {result.stderr.strip()}")
    else:
        raise RuntimeError("Ninguna voz de say funcionó")
    wav = FIXTURES / "sample_16k.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(aiff), "-ac", "1", "-ar", "16000", str(wav)],
        check=True,
    )
    return wav


def main():
    wav = make_sample()
    words = transcribe(wav, model_size="small")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "transcribe_sample.json").write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"palabras: {len(words)}")
    if words:
        print(f"primera: start={words[0]['start']} end={words[0]['end']} text={words[0]['text']!r}")


if __name__ == "__main__":
    main()
