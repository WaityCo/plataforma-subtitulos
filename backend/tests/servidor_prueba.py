"""Servidor de prueba para la toma del worker entre dos procesos (test_takeover_procesos.py).

Arranca la API sobre la carpeta de SUBS_DATA_DIR con un motor falso cuya transcripción dura SUBS_PRUEBA_TRANSCRIPCION_S
segundos (15 por defecto). Uso: python -m backend.tests.servidor_prueba PUERTO.
"""

import os
import sys
import time

import uvicorn

from backend.app import create_app
from backend.config import Settings
from backend.tests.fakes import FakeEngine


class MotorLento(FakeEngine):
    """El motor falso con una transcripción que dura: el job se queda en 'transcribing' mientras tanto."""

    def __init__(self, segundos: float) -> None:
        super().__init__()
        self.segundos = segundos

    def transcribe(self, **kwargs):
        time.sleep(self.segundos)
        return super().transcribe(**kwargs)


def main() -> None:
    puerto = int(sys.argv[1])
    segundos = float(os.environ.get("SUBS_PRUEBA_TRANSCRIPCION_S", "15"))
    app = create_app(settings=Settings.from_env(), engine=MotorLento(segundos))
    uvicorn.run(app, host="127.0.0.1", port=puerto, log_level="warning")


if __name__ == "__main__":
    main()
