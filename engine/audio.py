"""Extracción de audio y lectura de metadatos del video con FFmpeg y ffprobe."""

import json
import subprocess

from engine.ffbin import ffmpeg_bin, ffprobe_bin


def extract_audio(video_path, wav_path):
    """Escribe el audio del video como WAV mono de 16 kHz. Lanza RuntimeError con el stderr de FFmpeg."""
    cmd = [
        ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000",
        str(wav_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg falló al extraer el audio: {result.stderr.strip()}")


def has_audio(video_path):
    """True si el archivo tiene al menos un stream de audio, según ffprobe. Sin audio no hay nada que transcribir."""
    cmd = [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_streams", str(video_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe no pudo leer el video: {result.stderr.strip()}")
    streams = json.loads(result.stdout).get("streams", [])
    return any(stream.get("codec_type") == "audio" for stream in streams)


def probe_video(video_path):
    """Devuelve width, height y duration. Las dimensiones ya incluyen la rotación del teléfono."""
    cmd = [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(video_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe no pudo leer el video: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if stream is None:
        raise RuntimeError("El archivo no tiene stream de video")
    width, height = int(stream["width"]), int(stream["height"])
    if _rotation(stream) % 180 == 90:
        width, height = height, width
    duration = float(data.get("format", {}).get("duration", 0.0))
    return {"width": width, "height": height, "duration": duration}


def _rotation(stream):
    # FFmpeg gira el frame al decodificar; el lienzo ASS debe usar el tamaño ya girado.
    for side_data in stream.get("side_data_list", []):
        if "rotation" in side_data:
            return abs(int(side_data["rotation"]))
    return abs(int(stream.get("tags", {}).get("rotate", 0)))
