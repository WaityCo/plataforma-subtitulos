// Configuración del frontend. Se carga antes que js/app.js (script clásico, sin módulo).
//
// SUBS_API_BASE: origen del backend, sin barra final. "" = mismo origen: el backend sirve el frontend y así funciona en
// local. Con el frontend en otro origen (Cloudflare Pages), pon aquí la URL del backend. Ese backend tiene que responder
// CORS para el origen del frontend con credenciales: Access-Control-Allow-Origin con el origen exacto (no *) y
// Access-Control-Allow-Credentials: true. Las fuentes (/fonts/) también necesitan CORS, porque FontFace las pide con CORS.
window.SUBS_API_BASE = "";

// SUBS_LOCAL_URL: el Mac del servidor visto desde su propio navegador. El sitio público consulta /api/local-ping ahí para
// ofrecer la versión local. Tiene que usar el puerto del backend (BACKEND_PORT en deploy/cloudflare/common.sh).
window.SUBS_LOCAL_URL = "http://127.0.0.1:8765";
