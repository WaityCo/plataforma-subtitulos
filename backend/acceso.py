"""Acceso a la API. Tres piezas:

- Clave (SUBS_API_KEY): con la variable definida, /api/* y /fonts/* exigen la cabecera X-Subs-Key. Sin la variable, la
  clave no se comprueba.
- Modo local: una petición que sale directa del Mac (es_local) no pide clave y recibe la interfaz. Lo que llega por el
  túnel no es local: Cloudflare conserva el Host y añade sus cabeceras, así que la interfaz responde 404 por el túnel.
- PingLocal: GET /api/local-ping responde {"ok": true} al propio Mac, para que el sitio público ofrezca la versión local.
"""

import hashlib
import hmac
from urllib.parse import urlsplit

from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

CABECERA = b"x-subs-key"  # en ASGI, los nombres de cabecera van en minúsculas y como bytes
RUTAS_PROTEGIDAS = ("/api", "/fonts")
MENSAJE = "Falta la clave de acceso."
RUTA_PING = "/api/local-ping"
IPS_LOCALES = frozenset({"127.0.0.1", "::1"})
HOSTS_LOCALES = frozenset({"127.0.0.1", "::1", "localhost"})
# Cabeceras que solo añaden un proxy o Cloudflare. Si llega una, la petición ha pasado por el túnel.
PREFIJOS_DE_PROXY = (b"cf-", b"x-forwarded-")
CABECERAS_DE_PROXY = frozenset({b"cdn-loop", b"forwarded", b"x-real-ip", b"true-client-ip"})


def protegida(path: str) -> bool:
    """True si la ruta necesita la clave: la API y las fuentes, pero nunca / ni la interfaz."""
    return any(path == base or path.startswith(base + "/") for base in RUTAS_PROTEGIDAS)


def _valores(scope: Scope, nombre: bytes) -> list[str]:
    return [valor.decode("latin-1") for clave, valor in scope.get("headers", []) if clave == nombre]


def es_conexion_directa(scope: Scope) -> bool:
    """True si la petición sale del propio Mac: cliente en loopback, Host de loopback y ninguna cabecera de proxy."""
    cliente = scope.get("client")
    if not cliente or cliente[0] not in IPS_LOCALES:
        return False
    if any(clave.startswith(PREFIJOS_DE_PROXY) or clave in CABECERAS_DE_PROXY for clave, _ in scope.get("headers", [])):
        return False
    hosts = _valores(scope, b"host")
    if len(hosts) != 1:
        return False
    try:
        nombre = urlsplit("//" + hosts[0]).hostname
    except ValueError:
        return False
    return nombre in HOSTS_LOCALES


def es_local(scope: Scope) -> bool:
    """Modo local: conexión directa desde el Mac y, si la envía el navegador, un Origin igual al de la propia petición.

    Con el Origin se cierra el paso a otras webs abiertas en el mismo navegador (CSRF): su Origin nunca coincide."""
    if not es_conexion_directa(scope):
        return False
    origenes = _valores(scope, b"origin")
    if not origenes:
        return True
    host = _valores(scope, b"host")[0].lower()
    return len(origenes) == 1 and origenes[0].lower() == f"http://{host}"


class ClaveDeAcceso:
    """Middleware ASGI. Lo que no es local pide la clave en /api/* y /fonts/*, y el resto de rutas no existe.
    Compara la cabecera con la clave en tiempo constante y no toca el cuerpo de la petición."""

    def __init__(self, app: ASGIApp, clave: str) -> None:
        self.app = app
        self._resumen = hashlib.sha256(clave.encode("utf-8")).digest()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or es_local(scope):
            await self.app(scope, receive, send)
            return
        if not protegida(scope["path"]):
            # Fuera del Mac la interfaz no existe: 404, como si no estuviera montada.
            await JSONResponse({"detail": "Not Found"}, status_code=404)(scope, receive, send)
            return
        recibida = next((valor for nombre, valor in scope["headers"] if nombre == CABECERA), b"")
        # Se comparan resúmenes de igual longitud: ni el contenido ni la longitud de la clave se filtran por el tiempo.
        if hmac.compare_digest(hashlib.sha256(recibida).digest(), self._resumen):
            await self.app(scope, receive, send)
            return
        await JSONResponse({"detail": MENSAJE}, status_code=401)(scope, receive, send)


class PingLocal:
    """Middleware ASGI, el más externo. GET /api/local-ping responde {"ok": true} solo a conexiones directas desde el Mac.

    El sitio público lo llama desde el navegador del dueño, así que sus orígenes (SUBS_PUBLIC_ORIGINS) reciben CORS.
    Chrome exige Access-Control-Allow-Private-Network en el preflight para llegar a una dirección local."""

    def __init__(self, app: ASGIApp, origenes: tuple[str, ...]) -> None:
        self.app = app
        self.origenes = frozenset(origenes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != RUTA_PING:
            await self.app(scope, receive, send)
            return
        if not es_conexion_directa(scope):
            await JSONResponse({"detail": "Not Found"}, status_code=404)(scope, receive, send)
            return
        origen = (_valores(scope, b"origin") or [""])[0]
        permitido = origen in self.origenes
        cabeceras = {"Cache-Control": "no-store", "Vary": "Origin"}
        if permitido:
            cabeceras["Access-Control-Allow-Origin"] = origen
        if scope["method"] == "OPTIONS":
            if permitido:
                cabeceras["Access-Control-Allow-Methods"] = "GET"
                cabeceras["Access-Control-Allow-Private-Network"] = "true"
                cabeceras["Access-Control-Max-Age"] = "600"
            await Response(status_code=204, headers=cabeceras)(scope, receive, send)
        elif scope["method"] == "GET":
            await JSONResponse({"ok": True}, headers=cabeceras)(scope, receive, send)
        else:
            await JSONResponse({"detail": "Método no permitido."}, status_code=405, headers={"Allow": "GET, OPTIONS"})(
                scope, receive, send
            )
