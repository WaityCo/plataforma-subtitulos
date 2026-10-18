"""Validación de la subida por extensión y content-type (B2): un content-type genérico lo decide el contenido."""

import pytest

from backend.media import InvalidVideo, validate_upload


@pytest.mark.parametrize(
    "content_type", ["video/mp4", "application/octet-stream", "application/octet-stream; charset=binary", ""]
)
def test_content_type_correcto_o_generico_admite_la_extension(content_type):
    assert validate_upload("clip.mp4", content_type) == ".mp4"


@pytest.mark.parametrize(
    "filename, content_type",
    [("clip.mp4", "text/plain"), ("clip.mp4", "video/webm"), ("nota.txt", "application/octet-stream"), ("nota.txt", "")],
)
def test_content_type_incompatible_o_extension_invalida_se_rechazan(filename, content_type):
    with pytest.raises(InvalidVideo):
        validate_upload(filename, content_type)
