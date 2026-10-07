"""Almacenamiento de los tokens de Google por usuario.

Los tokens **nunca** viajan al navegador: el cliente solo ve una cookie
firmada con el `sub` de Google. El `refresh_token` vive en el servidor,
en un archivo por usuario con permisos `0600` bajo `{PURPLEMD_DIR}/auth/`.

¿Por qué acá y no en Drive? Porque el storage de PurpleMD *es* el Drive
del usuario: guardar el token que abre ese Drive dentro de ese mismo
Drive es un huevo y la gallina. Además así los tokens sobreviven a un
cambio de backend (`PURPLEMD_STORAGE`) y se borran al cerrar sesión
sin tocar las notas.

El nombre de archivo es el SHA-256 del `sub`: el identificador de
Google es seguro, pero hasheado además evita cualquier discusión sobre
caracteres en el nombre de un archivo y no filtra el identificador al
listar el directorio.
"""

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger("purplemd")

# Límite de cuentas guardadas en disco: un crecimiento sin tope es un
# DoS lento (regla 7 de `skills/seguridad/SKILL.md`). Mil cuentas
# reales es mucho para este producto; si se llega, el login nuevo
# responde 503 con el motivo en lugar de comerse el disco.
TOPE_CUENTAS = 1000

# Margen para refrescar antes de que venza el access token: una operación
# de Drive puede tardar y el token vence a los 3600 s.
MARGEN_REFRESCO_SEG = 120


@dataclass
class Cuenta:
    """Tokens y perfil de una cuenta de Google conectada."""

    sub: str
    email: str
    name: str
    picture: str
    access_token: str
    refresh_token: str
    expires_at: int
    scope: str = ""

    @property
    def vigente(self) -> bool:
        """¿El access token sigue sirviendo sin refrescar?"""
        return self.expires_at - MARGEN_REFRESCO_SEG > time.time()


@runtime_checkable
class AlmacenCuentas(Protocol):
    """Persistencia de las cuentas conectadas."""

    def guardar(self, cuenta: Cuenta) -> None: ...

    def obtener(self, sub: str) -> Cuenta | None: ...

    def borrar(self, sub: str) -> None: ...

    def hay_cuentas(self) -> bool: ...


def identificador_seguro(sub: str) -> str:
    """Hash del `sub` de Google, apto para usar como nombre de archivo o directorio.

    El identificador de Google es seguro, pero hasheado además evita
    cualquier discusión sobre caracteres en un nombre de ruta y no
    filtra el identificador al listar un directorio. Se usa tanto para
    el archivo de tokens como para la carpeta de datos de la cuenta.
    """
    return hashlib.sha256(sub.encode("utf-8")).hexdigest()


def _archivo(sub: str) -> str:
    """Nombre de archivo para un `sub`, sin caracteres discutibles."""
    return identificador_seguro(sub) + ".json"


class LimiteCuentasError(Exception):
    """Se superó el tope de cuentas conectadas."""


class CuentasEnDisco:
    """Una archivo JSON por cuenta en `{PURPLEMD_DIR}/auth/`."""

    def __init__(self, directorio: Path | None = None) -> None:
        """`directorio` inyectado para los tests; si falta se resuelve
        de `PURPLEMD_AUTH_DIR` o `{PURPLEMD_DIR}/auth` en cada operación."""
        self._inyectado = directorio

    def _directorio(self) -> Path:
        if self._inyectado is not None:
            return self._inyectado
        explicito = os.environ.get("PURPLEMD_AUTH_DIR", "").strip()
        base = Path(explicito) if explicito else Path(
            os.environ.get("PURPLEMD_DIR", "./local/purplemd")
        )
        return base / "auth"

    def _ruta(self, sub: str) -> Path:
        return self._directorio() / _archivo(sub)

    def _listar(self) -> list[Path]:
        directorio = self._directorio()
        if not directorio.is_dir():
            return []
        return sorted(directorio.glob("*.json"))

    def guardar(self, cuenta: Cuenta) -> None:
        """Escribe la cuenta de forma atómica y con permisos 0600.

        El temporal nace con `0600` vía `mkstemp` y no se relaja al
        hacer `replace`: otro usuario del mismo host no puede leer el
        refresh token ni siquiera durante la escritura.
        """
        directorio = self._directorio()
        directorio.mkdir(parents=True, exist_ok=True)
        destino = self._ruta(cuenta.sub)
        if not destino.exists() and len(self._listar()) >= TOPE_CUENTAS:
            raise LimiteCuentasError(f"ya hay {TOPE_CUENTAS} cuentas conectadas")
        descriptor, temporal = tempfile.mkstemp(dir=directorio, prefix=".", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as archivo:
                json.dump(asdict(cuenta), archivo, ensure_ascii=False)
                archivo.flush()
                os.fsync(archivo.fileno())
            Path(temporal).replace(destino)
        except BaseException:
            Path(temporal).unlink(missing_ok=True)
            raise
        try:
            os.chmod(destino, 0o600)
        except OSError:  # pragma: no cover - sistemas sin chmod
            logger.warning("no pude fijar 0600 en %s", destino)

    def obtener(self, sub: str) -> Cuenta | None:
        """Carga la cuenta; `None` si no existe o el archivo está roto.

        Un archivo corrupto no puede tumbar el arranque: se registra y
        se trata como «sin cuenta», que obliga a volver a conectar.
        """
        ruta = self._ruta(sub)
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            return Cuenta(**datos)
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("cuenta ilegible en %s: %s", ruta, exc)
            return None

    def borrar(self, sub: str) -> None:
        try:
            self._ruta(sub).unlink()
        except FileNotFoundError:
            pass

    def hay_cuentas(self) -> bool:
        """¿Hay al menos una cuenta guardada? Para `/health` sin red."""
        return bool(self._listar())


class CuentasEnMemoria:
    """Versión en RAM con tope, para tests y despliegues sin disco.

    No es autoritativo: al reiniciar se pierden y hay que volver a
    conectar. Eso es aceptable porque solo se usa donde el storage ya es
    efímero.
    """

    def __init__(self, tope: int = 128) -> None:
        self._tope = tope
        self._datos: dict[str, Cuenta] = {}
        self._lock = threading.Lock()

    def guardar(self, cuenta: Cuenta) -> None:
        with self._lock:
            if cuenta.sub not in self._datos and len(self._datos) >= self._tope:
                antiguo = next(iter(self._datos))
                logger.warning("tope de cuentas en memoria: se olvida %s", antiguo)
                del self._datos[antiguo]
            self._datos[cuenta.sub] = cuenta

    def obtener(self, sub: str) -> Cuenta | None:
        with self._lock:
            cuenta = self._datos.get(sub)
            if cuenta is not None:
                # Acceso reciente, que queda al final (orden de expulsión).
                self._datos[sub] = self._datos.pop(sub)
            return cuenta

    def borrar(self, sub: str) -> None:
        with self._lock:
            self._datos.pop(sub, None)

    def hay_cuentas(self) -> bool:
        with self._lock:
            return bool(self._datos)


def almacen_de_entorno() -> AlmacenCuentas:
    """Almacenamiento de cuentas según el entorno.

    Siempre disco: es la única decisión que no pierde la sesión de todo
    el mundo al reiniciar el contenedor, y `{PURPLEMD_DIR}` ya es un
    volumen montado en todos los despliegues.
    """
    return CuentasEnDisco()
