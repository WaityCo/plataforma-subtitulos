"""Pipeline de un job: audio, transcripción, subtítulos ASS y quemado con libass."""

import json
from pathlib import Path

from engine.ass_builder import build_ass
from engine.audio import extract_audio, has_audio, probe_video
from engine.burn import burn as burn_video
from engine.burn import is_available
from engine.hook import render_hook, validate_spec
from engine.styles import resolve
from engine.transcribe import transcribe

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"


def run_job(video_path, job_dir, preset="ken_remedie", overrides=None, language=None,
            model_size=None, preview_seconds=None, progress=None, burn=False, hook=None):
    """Genera words.json y subtitles.ass en job_dir y, con burn=True, output.mp4 quemado.

    progress(stage, percent) recibe audio, transcribe, subtitles y burn. preview_seconds solo
    acorta la salida del quemado: el audio y el ASS son completos. output_path es None sin quemado.
    hook es un gancho titular (ver engine.hook.render_hook) que se superpone solo con burn=True.
    hook_warnings lista los grafemas del gancho que ninguna fuente dibujó y se omitieron.
    """
    style = resolve(preset, overrides)  # falla antes de tocar el video
    if hook is not None:
        validate_spec(hook)
    video = Path(video_path)
    if not video.is_file():
        raise FileNotFoundError(f"No existe el video: {video}")
    if burn and not is_available():
        raise RuntimeError("Quemar requiere un ffmpeg con libass (ffmpeg-full de Homebrew).")
    job = Path(job_dir).resolve()
    job.mkdir(parents=True, exist_ok=True)
    report = progress or (lambda stage, percent: None)

    media = probe_video(video)

    audible = has_audio(video)
    report("audio", 0.0)
    wav_path = job / "audio.wav"
    if audible:
        extract_audio(video, wav_path)
    report("audio", 100.0)

    report("transcribe", 0.0)
    # Sin pista de audio no hay palabras: words.json queda vacío y el ASS sin eventos; el job termina igual.
    words = transcribe(wav_path, language=language, model_size=model_size) if audible else []
    report("transcribe", 100.0)

    report("subtitles", 0.0)
    ass_text = build_ass(words, style, media["width"], media["height"])
    words_path = job / "words.json"
    ass_path = job / "subtitles.ass"
    words_path.write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")
    ass_path.write_text(ass_text, encoding="utf-8")
    report("subtitles", 100.0)

    output_path = None
    hook_warnings = []
    if burn:
        output = job / "output.mp4"
        overlays = ()
        if hook:
            overlays = render_hook(hook, media["width"], media["height"], out_dir=job / "hook")
            hook_warnings = overlays.warnings
        burn_video(video, ass_text, output, FONTS_DIR, preview_seconds=preview_seconds, progress=report,
                   overlays=overlays)
        output_path = str(output)
    return {
        "output_path": output_path,
        "words_path": str(words_path),
        "ass_path": str(ass_path),
        "duration_seconds": media["duration"],
        "hook_warnings": hook_warnings,
    }
