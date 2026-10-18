"""Los 7 presets previos siguen generando el mismo ASS que antes de añadir ken_remedie.

Las huellas son SHA-256 del ASS que producía el motor previo a ken_remedie
con la misma lista de palabras de test_ass_builder.SAMPLE. Si un cambio de render las mueve, o el cambio
es intencionado y se actualiza aquí, o es una regresión.
"""

import hashlib

import pytest

from engine.ass_builder import build_ass
from engine.styles import resolve

SAMPLE = [
    ("Hoy", 0.0, 0.3), ("te", 0.3, 0.5), ("comparto", 0.5, 1.0), ("tres", 1.0, 1.3), ("formas.", 1.3, 1.8),
    ("Respira", 2.4, 2.9), ("despacio", 2.9, 3.5), ("y", 3.5, 3.6), ("suelta", 3.6, 4.1),
    ("los", 4.1, 4.2), ("hombros.", 4.2, 4.9), ("Después", 5.0, 5.5), ("duerme", 5.5, 6.0), ("mejor", 6.0, 6.5),
]

DIGESTS = {
    ("ken_classic", 1080, 1920): "b9ad5796a8920850d6ee7acfddf5f40885aecb126e96265823bb27d90be41c13",
    ("ken_classic", 720, 1280): "a4bddfecfe51a7332a0cfff32fdb43b6df071316d9ae9adf1282cbbc768052ba",
    ("serif_glow", 1080, 1920): "84f34b1b49c44ffc7c8d0631b2f5e9fc1a2629e1dab296f91a8b078366b503df",
    ("serif_glow", 720, 1280): "724f0c846e84578fa67a86e5552bfa421a5506fc3c636f1e6f41fdefd19dc5bd",
    ("bold_karaoke", 1080, 1920): "c33fc2e4e91f7cc9f03b8ec7e28a86095ececee1def8e3271417f16919ca1f4b",
    ("bold_karaoke", 720, 1280): "527e1d86899e47f829d4f19d910cc03c24956830098d79309995f9a5a54a62bb",
    ("phrase_box", 1080, 1920): "2a54cf13bfce87a204455ec782ed4514831fc64e6a25a535d4daa73c7461f32b",
    ("phrase_box", 720, 1280): "4473dbc0a20acaec4b01d41d71b598bfb5bb0c83b25465ae9c342245120634b5",
    ("bold_caps_pop", 1080, 1920): "1499d7f0f41759390d5b15c2153dd93622d99230ca6ff069a6b0fd27b32c3423",
    ("bold_caps_pop", 720, 1280): "b09a8da960e34dec279f7019c027b48ac308c3cd3868307f94336ab569078d83",
    ("wellness_soft", 1080, 1920): "7abeba64c6553fe587d4af8f3c9ef973b5b04a445db29752ae00776529cf21e1",
    ("wellness_soft", 720, 1280): "83cb9aaab7b93a882bc72407f81bae21fe57d32454d77ce3bc124befa220ca8d",
    ("minimal_mono", 1080, 1920): "9490b439ec5dc158660916f0da947d7a9fe5d36971a4b4eecf6a5bb940cf972d",
    ("minimal_mono", 720, 1280): "59696655e8315a4af8ad9c4b4479e93040dc62fbaca7b52c84d51b87b1306964",
}


@pytest.mark.parametrize(("preset", "width", "height"), list(DIGESTS))
def test_previous_preset_output_is_byte_identical(preset, width, height):
    words = [{"text": text, "start": start, "end": end} for text, start, end in SAMPLE]
    text = build_ass(words, resolve(preset), width, height)
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == DIGESTS[(preset, width, height)]
