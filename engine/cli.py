"""CLI del motor: python -m engine.cli INPUT.mp4 --preset NAME --out-dir DIR [--set campo=valor] [--no-burn]"""

import argparse
import json
import sys

from engine.pipeline import run_job


def _parse_set(item):
    key, sep, raw = item.partition("=")
    if not sep or not key.strip():
        raise argparse.ArgumentTypeError(f"--set espera campo=valor; llegó {item!r}")
    try:
        value = json.loads(raw)  # 86, true, null... Lo que no es JSON queda como texto.
    except json.JSONDecodeError:
        value = raw
    return key.strip(), value


def main(argv=None):
    parser = argparse.ArgumentParser(description="Genera subtítulos ASS para un video vertical.")
    parser.add_argument("input", help="Video de entrada")
    parser.add_argument("--preset", default="ken_remedie", help="Nombre del preset")
    parser.add_argument("--out-dir", required=True, help="Carpeta del job")
    parser.add_argument("--set", dest="overrides", action="append", default=[], type=_parse_set,
                        metavar="campo=valor", help="Override de estilo; se puede repetir")
    parser.add_argument("--no-burn", action="store_true",
                        help="No quemar el video; solo words.json y subtitles.ass")
    args = parser.parse_args(argv)

    def report(stage, percent):
        print(f"{stage}: {percent:.0f}%", file=sys.stderr)

    try:
        result = run_job(
            args.input,
            args.out_dir,
            preset=args.preset,
            overrides=dict(args.overrides),
            progress=report,
            burn=not args.no_burn,
        )
    except (FileNotFoundError, NotImplementedError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
