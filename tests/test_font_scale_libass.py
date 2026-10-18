import pytest

from engine.burn import is_available
from engine.textmetrics import font_catalog
from libass_probe import probe_font

pytestmark = pytest.mark.skipif(not is_available(), reason="el ffmpeg resuelto no tiene libass")

CATALOG = font_catalog()


@pytest.mark.parametrize("index", range(len(CATALOG)), ids=[entry["file"] for entry in CATALOG])
def test_css_scale_and_line_height_match_libass_within_2_percent(index):
    row = probe_font(index, CATALOG[index])
    assert abs(row["err_h_pct"]) < 2.0, row
    assert abs(row["err_line_pct"]) < 2.0, row
