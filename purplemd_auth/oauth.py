"""Cliente OAuth 2.0 de Google: Authorization Code con PKCE.

Todo el flujo corre **del lado del servidor** con `httpx` (sin librerías
de Google, sin JS en el cliente):

1. `GET /api/auth/login` construye la URL de consentimiento con un
   `state` aleatorio y un `code_challenge` PKCE.
2. `GET /api/auth/callback` cambia el `code` por tokens y guarda el
   `refresh_token` en el servidor.
3. Cada operación contra Drive usa el access token vigente y lo
   refresca por su cuenta cuando está por vencer.

PKCE (`code_verifier` local, `code_challenge` en la URL) protege el
intercambio contra un código interceptado: aunque un atacante vea la
redirección, no tiene el verifier. `state` cubre el otro flanco, el
CSRF del propio flujo (que alguien dispare el callback con una sesión
ajena).

Referencia: RFC 7636 y la documentación de Google «Authorization Code
Grant Type».
"""

import base64
import hashlib
import logging
import secrets
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

from purplemd_auth.config import URL_AUTORIZACION, URL_PERFIL, URL_TOKEN, ConfigAuth
from purplemd_auth.tokens import AlmacenCuentas

logger = logging.getLogger("purplemd")

# Google responde rápido pero detrás de un proxy puede tardar; 15 s es
# cómodo sin dejar un request colgado indefinidamente.
TIMEOUT = httpx.Timeout(15.0)

# Pool de conexiones compartido por todo el proceso.
_CLIENTE: httpx.Client | None = None
_CANDADO = threading.Lock()


class OAuthError(Exception):
    """Fallo atribuible al flujo de Google (no a PurpleMD).

    El mensaje va al usuario, así que nunca lleva el client secret ni
    el refresh token: solo lo que Google ya mostró en pantalla.
    """


def cliente_por_defecto() -> httpx.Client:
    """Cliente HTTP compartido para reusar conexiones entre requests.

    Los tests lo reemplazan por uno con `httpx.MockTransport`, así que
    cualquier llamada a Google pasa por acá y puede interceptarse.
    """
    global _CLIENTE
    with _CANDADO:
        if _CLIENTE is None:
            _CLIENTE = httpx.Client(timeout=TIMEOUT)
        return _CLIENTE


def nuevo_verifier() -> str:
    """`code_verifier` de PKCE: 64 bytes aleatorios en base64url."""
    return secrets.token_urlsafe(64)


def challenge_de(verifier: str) -> str:
    """`code_challenge` S256: base64url(SHA-256(verifier)) sin padding."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def nuevo_state() -> str:
    """Estado aleatorio para atar el callback a esta pestaña."""
    return secrets.token_urlsafe(32)


def url_autorizacion(
    config: ConfigAuth, redirect_uri: str, state: str, verifier: str
) -> str:
    """URL de consentimiento de Google.

    - `access_type=offline` pide refresh token (sin él, la sesión moriría
      a la hora).
    - `prompt=consent` garantiza que Google entregue el refresh token
      aunque el usuario ya haya autorizado la app antes; sin él, Google
      lo omite en autorizaciones repetidas y Drive quedaría sin credencial
      de larga duración. Cuesta una pantalla más al ingresar, y a cambio
      la sesión dura 30 días.
    """
    params = {
        "client_id": config.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": config.alcance,
        "state": state,
        "code_challenge": challenge_de(verifier),
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{URL_AUTORIZACION}?{httpx.QueryParams(params)}"


def _intercambio(config: ConfigAuth, datos: dict[str, str]) -> dict[str, Any]:
    """POST al endpoint de tokens de Google con manejo de error."""
    try:
        respuesta = cliente_por_defecto().post(
            URL_TOKEN,
            data={
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                **datos,
            },
        )
    except httpx.HTTPError as exc:
        # Red caída o timeout: el mensaje no lleva datos sensibles.
        logger.warning("no se pudo contactar con el endpoint de tokens: %s", exc)
        raise OAuthError("no se pudo contactar con Google") from exc

    if respuesta.status_code != 200:
        raise OAuthError(_motivo(respuesta))
    try:
        cuerpo = respuesta.json()
    except ValueError as exc:
        raise OAuthError("Google devolvió una respuesta que no es JSON") from exc
    if not isinstance(cuerpo.get("access_token"), str):
        raise OAuthError("Google no devolvió un access token")
    return cuerpo


def _motivo(respuesta: httpx.Response) -> str:
    """Extrae `error_description` de Google sin volcar el cuerpo entero."""
    try:
        cuerpo = respuesta.json()
    except ValueError:
        return f"Google respondió HTTP {respuesta.status_code}"
    descripcion = cuerpo.get("error_description") or cuerpo.get("error")
    if isinstance(descripcion, str) and descripcion:
        return descripcion
    return f"Google respondió HTTP {respuesta.status_code}"


def intercambiar_codigo(
    config: ConfigAuth, redirect_uri: str, codigo: str, verifier: str
) -> dict[str, Any]:
    """Cambia el `code` del callback por access y refresh token."""
    return _intercambio(
        config,
        {
            "grant_type": "authorization_code",
            "code": codigo,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
    )


def refrescar(config: ConfigAuth, refresh_token: str) -> dict[str, Any]:
    """Obtiene un access token nuevo a partir del refresh token."""
    return _intercambio(
        config,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )


def perfil(access_token: str) -> dict[str, Any]:
    """Pide el perfil (`sub`, `email`, `name`, `picture`) del usuario.

    El `sub` es el identificador estable con el que PurpleMD aísla los
    datos: el email se puede cambiar, el sub no.
    """
    try:
        respuesta = cliente_por_defecto().get(
            URL_PERFIL, headers={"Authorization": f"Bearer {access_token}"}
        )
    except httpx.HTTPError as exc:
        logger.warning("no se pudo obtener el perfil de Google: %s", exc)
        raise OAuthError("no se pudo obtener tu cuenta de Google") from exc
    if respuesta.status_code != 200:
        raise OAuthError(_motivo(respuesta))
    try:
        datos = respuesta.json()
    except ValueError as exc:
        raise OAuthError("Google devolvió un perfil ilegible") from exc
    if not isinstance(datos.get("sub"), str) or not datos["sub"]:
        raise OAuthError("Google no devolvió un identificador de cuenta")
    return datos


def proveedor_vigente(
    config: ConfigAuth, almacen: AlmacenCuentas, sub: str
) -> Callable[[], str]:
    """Devuelve un callable que entrega un access token siempre vigente.

    Es el puente entre `purplemd_auth` (dueño de los tokens) y
    `purplemd_storage` (que solo sabe pedir «un token, ya»). Refresca
    cuando el guardado está por vencer y **persiste el nuevo**, porque
    Google lo emite con un `refresh_token` que puede rotar: si no se
    guardara, la sesión moriría al próximo reinicio.

    Si el refresh falla (consentimiento revocado, app en testing pasados
    los 7 días), lanza `OAuthError`: el caller lo traduce en un 401 y
    el usuario vuelve a conectar su cuenta.
    """

    def proveedor() -> str:
        cuenta = almacen.obtener(sub)
        if cuenta is None:
            raise OAuthError("tu cuenta de Google no está conectada en este servidor")
        if cuenta.vigente:
            return cuenta.access_token
        if not cuenta.refresh_token:
            raise OAuthError("falta la credencial de larga duración: volvé a conectar tu cuenta")
        datos = refrescar(config, cuenta.refresh_token)
        cuenta.access_token = str(datos["access_token"])
        cuenta.expires_at = int(time.time()) + int(datos.get("expires_in", 3600))
        if isinstance(datos.get("refresh_token"), str):
            cuenta.refresh_token = datos["refresh_token"]
        almacen.guardar(cuenta)
        return cuenta.access_token

    return proveedor
