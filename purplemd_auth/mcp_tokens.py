"""Token del servidor MCP: uno firmado por cuenta, sin estado en el servidor.

Un cliente MCP no trae cookie de sesión, así que se autentica con un token
propio que la **app emite para la cuenta logueada** (el botón del menú). El
token es un payload firmado con `PURPLEMD_SECRET_KEY` —el mismo primitivo HMAC
de la sesión— que lleva el `sub` de Google y un alcance propio:

- **Alcance `mcp`**: una cookie de sesión no sirve como token MCP ni al revés,
  aunque compartan clave y formato. Cada uno abre solo lo que le corresponde.
- **Sin estado**: no hay tabla de tokens que crecer ni que vencer; emitir es
  firmar (regla 7 de `skills/seguridad/SKILL.md`).
- **Revocación**: rotar `PURPLEMD_SECRET_KEY` vence todos los tokens a la vez
  (y cierra todas las sesiones); el TTL acota el daño en el camino.

Qué identifica cada token:

| Token | Quién lo tiene | Qué abre |
|---|---|---|
| Este (firmado, con `sub`) | la persona logueada | la carpeta (o el Drive) de **su cuenta** |
| `PURPLEMD_MCP_TOKEN` (entorno) | el admin | solo despliegues **sin cuenta**: la raíz |

Con login encendido el token de entorno no sirve: no identifica a nadie y la
única carpeta que alcanzaría es la raíz de la era sin login. Ver `docs/AUTH.md`.
"""

from typing import Any

from purplemd_auth.sesiones import firmar, verificar

# Alcance propio del token MCP: separa este payload de una sesión (`sub`
# pero sin `alcance`) para que los dos no sean intercambiables.
ALCANCE_MCP = "mcp"

# 90 días: vive en el `claude_desktop_config.json` de la persona, así que
# tiene que durar como para no ser una molestia diaria, pero no indefinido.
TTL_TOKEN_MCP_SEG = 90 * 24 * 3600


def crear_token_mcp(sub: str, secreto: str, ahora: float | None = None) -> str:
    """Firma el token MCP de una cuenta.

    Args:
        sub: Identificador de Google de la cuenta dueña de los datos.
        secreto: Clave de `PURPLEMD_SECRET_KEY`.
        ahora: Reloj inyectable para los tests.

    Returns:
        Token `payload_firmado.firma` listo para la cabecera
        `X-PurpleMD-Token`.
    """
    if not sub or not secreto:
        raise ValueError("un token MCP necesita sub y secreto")
    return firmar({"sub": sub, "alcance": ALCANCE_MCP}, secreto, TTL_TOKEN_MCP_SEG, ahora)


def verificar_token_mcp(
    token: str | None, secreto: str, ahora: float | None = None
) -> dict[str, Any] | None:
    """Valida un token MCP y devuelve su payload, o `None`.

    Devolver `None` en vez de lanzar es deliberado (igual que `verificar`):
    cualquier token ausente, alterado, vencido o con otro alcance es simplemente
    «no soy nadie», y el caller decide si eso es un 401 o un 403.
    """
    if not token or not secreto:
        return None
    payload = verificar(token, secreto, ahora)
    if payload is None or payload.get("alcance") != ALCANCE_MCP:
        return None
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        return None
    return payload
