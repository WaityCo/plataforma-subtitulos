"""Clave de acceso opcional (SUBS_API_KEY). Si está definida, /api/* y /fonts/* exigen la cabecera X-Subs-Key con ese
valor. / y la interfaz estática siguen públicos. Sin la variable, este módulo no se usa."""

import hashlib
import hmac

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

CABECERA = b"x-subs-key"  # en ASGI, los nombres de cabecera van en minúsculas y como bytes
RUTAS_PROTEGIDAS = ("/api", "/fonts")
MENSAJE = "Falta la clave de acceso."


def protegida(path: str) -> bool:
    """True si la ruta necesita la clave: la API y las fuentes, pero nunca / ni la interfaz."""
    return any(path == base or path.startswith(base + "/") for base in RUTAS_PROTEGIDAS)


class ClaveDeAcceso:
    """Middleware ASGI. Compara la cabecera con la clave en tiempo constante y no toca el cuerpo de la petición."""

    def __init__(self, app: ASGIApp, clave: str) -> None:
        self.app = app
        self._resumen = hashlib.sha256(clave.encode("utf-8")).digest()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not protegida(scope["path"]):
            await self.app(scope, receive, send)
            return
        recibida = next((valor for nombre, valor in scope["headers"] if nombre == CABECERA), b"")
        # Se comparan resúmenes de igual longitud: ni el contenido ni la longitud de la clave se filtran por el tiempo.
        if hmac.compare_digest(hashlib.sha256(recibida).digest(), self._resumen):
            await self.app(scope, receive, send)
            return
        await JSONResponse({"detail": MENSAJE}, status_code=401)(scope, receive, send)
