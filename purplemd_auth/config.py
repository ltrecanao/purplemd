"""Configuración de la integración con Google, leída del entorno.

La integración es **opt-in**: sin credenciales el comportamiento de
PurpleMD es idéntico al histórico (sin login, sin usuarios, la demo
pública sigue funcionando). Solo cuando hay credenciales completas la
app empieza a exigir sesión.

Ningún secreto vive en el repo: `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET` y `PURPLEMD_SECRET_KEY` vienen del entorno
(Dockerfile, Render, CI) y `.gitignore` ya cubre `.env`.

Variables:

| Variable | Obligatoria | Qué hace |
|---|---|---|
| `GOOGLE_CLIENT_ID` | sí¹ | Client ID de la consola de Google Cloud |
| `GOOGLE_CLIENT_SECRET` | sí¹ | Client Secret correspondiente |
| `PURPLEMD_SECRET_KEY` | sí¹ | Clave con la que se firman las cookies de sesión |
| `PURPLEMD_AUTH` | no | `off` fuerza el apagado, `on` fuerza el encendido |
| `PURPLEMD_REDIRECT_URI` | no | URI registrada en Google; si falta, se deriva del request |
| `PURPLEMD_GOOGLE_SCOPE` | no | Alcance por defecto de Google (incluye Drive) |

¹ Obligatorias para que la integración esté habilitada; sin ellas nada
se rompe, simplemente no hay login.
"""

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger("purplemd")

# Endpoints de Google. Están acá y no en `oauth.py` para que la
# configuración sea el único lugar que define «contra quién» hablamos.
URL_AUTORIZACION = "https://accounts.google.com/o/oauth2/v2/auth"
URL_TOKEN = "https://oauth2.googleapis.com/token"
URL_PERFIL = "https://openidconnect.googleapis.com/v1/userinfo"

# Alcance mínimo que cubre identidad + la carpeta donde viven las notas.
#
# `drive.file` (y no `drive`) hace que el consentimiento muestre «acceso
# a los archivos que creó esta app» y no a todo el Drive.
#
# `drive.appdata` es el requisito explícito de Google para tocar
# `appDataFolder` (guía «Store application-specific data»: «Before you
# can access the application data folder, you must request access to the
# drive.appdata scope»). Sin él, `files.list` sobre la carpeta oculta
# devuelve vacía. Es un alcance *non-sensitive*: no exige verificación
# ni agrega pantalla de advertencia.
SCOPE_DEFECTO = (
    "openid email profile "
    "https://www.googleapis.com/auth/drive.file "
    "https://www.googleapis.com/auth/drive.appdata"
)

# Valores que apagan la integración aunque haya credenciales.
_APAGADO = {"off", "0", "no", "false", "apagado"}
# Valores que la encienden aunque falte algo: si falta, se registra el
# motivo y queda apagada (nunca se levanta una app que cree que tiene
# login y no lo tiene).
_ENCENDIDO = {"on", "1", "si", "sí", "yes", "true", "encendido"}


@dataclass(frozen=True)
class ConfigAuth:
    """Configuración resuelta de la integración con Google.

    `client_secret` y `secret_key` van `repr=False`: un `ConfigAuth` en
    un traceback, en un log o en un debugger no puede volcar los
    secretos (regla 4 de `skills/seguridad/SKILL.md`).
    """

    habilitado: bool
    client_id: str
    client_secret: str = field(repr=False)
    secret_key: str = field(repr=False)
    redirect_uri: str
    alcance: str

    @property
    def drive_habilitado(self) -> bool:
        """True si el alcance incluye acceso a Google Drive."""
        return "drive" in self.alcance


def _leer(nombre: str) -> str:
    """Variable de entorno recortada; vacío si no está definida."""
    return os.environ.get(nombre, "").strip()


def desde_entorno() -> ConfigAuth:
    """Resuelve la configuración actual leyendo `os.environ`.

    Se lee en cada llamada (igual que `get_storage()`) para que los
    cambios de entorno surtan efecto en caliente, que es como trabaja la
    suite: `patch.dict(os.environ, ...)` por test.

    Si falta cualquier pieza, devuelve `habilitado=False` y registra el
    motivo en `WARNING`: una integración silenciosamente rota es un bug
    invisible en producción.
    """
    client_id = _leer("GOOGLE_CLIENT_ID")
    client_secret = _leer("GOOGLE_CLIENT_SECRET")
    secret_key = _leer("PURPLEMD_SECRET_KEY")
    redirect_uri = _leer("PURPLEMD_REDIRECT_URI")
    alcance = _leer("PURPLEMD_GOOGLE_SCOPE") or SCOPE_DEFECTO
    selector = _leer("PURPLEMD_AUTH").lower()

    if selector in _APAGADO:
        return ConfigAuth(False, client_id, client_secret, secret_key, redirect_uri, alcance)

    faltantes = [
        nombre
        for nombre, valor in (
            ("GOOGLE_CLIENT_ID", client_id),
            ("GOOGLE_CLIENT_SECRET", client_secret),
            ("PURPLEMD_SECRET_KEY", secret_key),
        )
        if not valor
    ]
    if not faltantes:
        return ConfigAuth(True, client_id, client_secret, secret_key, redirect_uri, alcance)

    # Nada configurado y nadie lo pidió: es el despliegue normal sin
    # login, no hay nada que registrar.
    pedido = bool(client_id or client_secret or secret_key) or selector in _ENCENDIDO
    if not pedido:
        return ConfigAuth(False, client_id, client_secret, secret_key, redirect_uri, alcance)

    # Mitad configurado: dejarlo pasar en silencio sería un login que
    # nunca aparece y nadie sabe por qué (regla 4 de la skill de seguridad).
    logger.warning(
        "la integración con Google queda apagada porque faltan %s%s",
        ", ".join(faltantes),
        f" (PURPLEMD_AUTH={selector})" if selector else "",
    )
    return ConfigAuth(False, client_id, client_secret, secret_key, redirect_uri, alcance)
