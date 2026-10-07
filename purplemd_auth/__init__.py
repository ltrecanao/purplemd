"""Autenticación de PurpleMD con Google (OAuth 2.0 + Drive).

Paquete opt-in: sin `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` /
`PURPLEMD_SECRET_KEY` en el entorno, `desde_entorno().habilitado` es
`False` y PurpleMD se comporta exactamente como antes (sin usuarios).
"""

from purplemd_auth.config import (
    SCOPE_DEFECTO,
    URL_AUTORIZACION,
    URL_PERFIL,
    URL_TOKEN,
    ConfigAuth,
    desde_entorno,
)
from purplemd_auth.oauth import (
    OAuthError,
    challenge_de,
    intercambiar_codigo,
    nuevo_state,
    nuevo_verifier,
    perfil,
    proveedor_vigente,
    refrescar,
    url_autorizacion,
)
from purplemd_auth.sesiones import (
    COOKIE_OAUTH,
    COOKIE_SESION,
    TTL_OAUTH_SEG,
    TTL_SESION_SEG,
    cookie_segura,
    es_https,
    firmar,
    verificar,
)
from purplemd_auth.tokens import (
    AlmacenCuentas,
    Cuenta,
    CuentasEnDisco,
    CuentasEnMemoria,
    LimiteCuentasError,
    almacen_de_entorno,
    identificador_seguro,
)

__all__ = [
    "AlmacenCuentas",
    "ConfigAuth",
    "COOKIE_OAUTH",
    "COOKIE_SESION",
    "Cuenta",
    "CuentasEnDisco",
    "CuentasEnMemoria",
    "OAuthError",
    "LimiteCuentasError",
    "SCOPE_DEFECTO",
    "TTL_OAUTH_SEG",
    "TTL_SESION_SEG",
    "URL_AUTORIZACION",
    "URL_PERFIL",
    "URL_TOKEN",
    "almacen_de_entorno",
    "challenge_de",
    "cookie_segura",
    "desde_entorno",
    "es_https",
    "firmar",
    "identificador_seguro",
    "intercambiar_codigo",
    "nuevo_state",
    "nuevo_verifier",
    "perfil",
    "proveedor_vigente",
    "refrescar",
    "url_autorizacion",
    "verificar",
]
