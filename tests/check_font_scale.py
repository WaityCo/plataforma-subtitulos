"""Imprime cuánto se aleja font_catalog() de libass, fuente por fuente. No forma parte de pytest.

Uso: .venv/bin/python tests/check_font_scale.py
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from engine.textmetrics import font_catalog  # noqa: E402
from libass_probe import probe_font  # noqa: E402


def main():
    header = (f"{'archivo':28} {'css_scale':>9} {'H pred px':>9} {'H libass':>9} {'err H %':>8} "
              f"{'line_h':>7} {'paso libass':>11} {'err paso %':>10}")
    print(header)
    print("-" * len(header))
    for index, entry in enumerate(font_catalog()):
        row = probe_font(index, entry)
        print(f"{row['file']:28} {row['css_scale']:9.4f} {row['h_predicted']:9.2f} {row['h_measured']:9.2f} "
              f"{row['err_h_pct']:8.2f} {row['line_height']:7.4f} {row['line_measured']:11.4f} "
              f"{row['err_line_pct']:10.2f}")


if __name__ == "__main__":
    main()
