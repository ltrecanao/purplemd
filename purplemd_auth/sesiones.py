"""Sesiones de PurpleMD: cookies firmadas con HMAC-SHA256.

Una sesión es un payload JSON firmado con `PURPLEMD_SECRET_KEY` y
viaja en una cookie `HttpOnly; SameSite=Lax`. Sin dependencias nuevas:
todo el primitivo (HMAC, base64, json) viene de la librería estándar.

Por qué cookie firmada y no JWT: el servidor es el único que emite y
lee la sesión, no hay que rotar claves ni validar `kid`, y el estado
no viaja por el cliente. Al ser opaco, un JWT no aportaría nada.

Seguridad (reglas 6 y 7 de `skills/seguridad/SKILL.md`):

- **Firma** con `hmac.compare_digest`: una cookie alterada no es una
  sesión, se ignora en lugar de lanzar.
- **`HttpOnly`**: el JavaScript del frontend nunca lee el token.
- **`SameSite=Lax`**: el navegador no lo envía en peticiones
  cross-site, que es la primera barrera contra CSRF.
- **Expiración** embebida (`exp`): no hace falta estado del lado del
  servidor para vencer una sesión.
- El `state` del flujo OAuth vive en una cookie aparte y con TTL corto,
  para que un callback ajeno no pueda completar un login.
"""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

# Cookies distintas para sesiones y para el flujo OAuth: la del flujo
# se borra al terminar y su TTL es minutos, no días.
COOKIE_SESION = "purplemd_sesion"
COOKIE_OAUTH = "purplemd_oauth"

# 30 días. Si la app de Google está en modo «testing», Google entrega
# refresh tokens de 7 días y el usuario deberá reingresar antes: eso es
# una política de Google, no de PurpleMD (ver docs/AUTH.md).
TTL_SESION_SEG = 30 * 24 * 3600
# Ventana para completar el redireccionamiento contra Google.
TTL_OAUTH_SEG = 600

_CLAVES_FIRMADAS = ("exp",)


def _b64(datos: bytes) -> str:
    """Base64 URL-safe sin padding: la cookie tiene que sobrevivir a URLs."""
    return base64.urlsafe_b64encode(datos).decode("ascii").rstrip("=")


def _desb64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def firmar(payload: dict[str, Any], secreto: str, ttl: int, ahora: float | None = None) -> str:
    """Firma `payload` con `exp` calculado desde `ahora` + `ttl`.

    Args:
        payload: Datos a embeber. No debe contener `exp` ya puesto.
        secreto: Clave de `PURPLEMD_SECRET_KEY`.
        ttl: Validez en segundos.
        ahora: Reloj inyectable para los tests.

    Returns:
        Token `payload_firmado.firma` listo para la cookie.
    """
    cuerpo = dict(payload)
    cuerpo["exp"] = int((ahora if ahora is not None else time.time()) + ttl)
    serializado = json.dumps(cuerpo, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    datos = _b64(serializado.encode("utf-8"))
    firma = hmac.new(secreto.encode("utf-8"), datos.encode("ascii"), hashlib.sha256).digest()
    return f"{datos}.{_b64(firma)}"


def verificar(
    token: str | None, secreto: str, ahora: float | None = None
) -> dict[str, Any] | None:
    """Valida un token firmado y devuelve su payload, o `None`.

    Exige solo `exp`, porque este módulo firma dos cosas distintas: la
    sesión (que sí tiene `sub`, `email`, ...) y la ventana corta del
    flujo OAuth (con `state` y `verifier`). Cada caller decide qué
    claves necesita; acá se garantiza que el payload es un objeto con
    vencimiento y que la firma no se tocó.

    Devolver `None` en vez de lanzar es deliberado: cualquier token
    corrupto, alterado o vencido es simplemente «sin sesión», y el
    caller decide si eso es un 401 o el modo invitado.
    """
    if not token or not secreto or "." not in token:
        return None
    datos, _, firma = token.partition(".")
    if not datos or not firma:
        return None
    esperada = hmac.new(secreto.encode("utf-8"), datos.encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64(esperada), firma):
        return None
    try:
        payload = json.loads(_desb64(datos))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if any(clave not in payload for clave in _CLAVES_FIRMADAS):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp <= (ahora if ahora is not None else time.time()):
        return None
    return payload


def cookie_segura(es_https: bool) -> dict[str, Any]:
    """Atributos de cookie para `Response.set_cookie`.

    `Secure` solo cuando el request llega por HTTPS: marcarla siempre
    dejaría sin sesión a cualquier despliegue en `http://` (la demo, el
    desarrollo local), que es exactamente lo que no queremos romper.
    """
    return {
        "httponly": True,
        "samesite": "lax",
        "path": "/",
        "secure": es_https or _leer("PURPLEMD_COOKIE_SECURE"),
    }


def _leer(nombre: str) -> bool:
    return os.environ.get(nombre, "").strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


def es_https(request: Any) -> bool:
    """¿El request llegó por HTTPS?

    Uvicorn con `--proxy-headers` (así corre en el contenedor) respeta
    `X-Forwarded-Proto`, así que detrás de un proxy el esquema que ve
    Starlette ya es el público.
    """
    return request.url.scheme == "https"
