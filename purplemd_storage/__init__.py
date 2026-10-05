"""Abstracción de almacenamiento para PurpleMD.

Define el protocolo `Storage` y la factory `get_storage()` que selecciona el
backend según la variable de entorno `PURPLEMD_STORAGE` (valores: "filesystem"
o "memory"). Por defecto usa "filesystem".
"""

import os

from purplemd_storage.filesystem import FilesystemStorage
from purplemd_storage.memory import MemoryStorage
from purplemd_storage.protocol import (
    DIR_DEFECTO,
    DIR_PROYECTOS,
    EXTENSION,
    MAX_BYTES,
    MAX_IMPORT_TOTAL_BYTES,
    MAX_IMPORT_ZIP_BYTES,
    MAX_PROFUNDIDAD,
    MAX_RUTA_BYTES,
    Arbol,
    DestinoOcupado,
    Directorio,
    DirectorioNoEncontrado,
    DirectorioNoVacio,
    Entrada,
    MovimientoInvalido,
    NombreInvalido,
    Nota,
    NotaDemasiadoGrande,
    NotaNoEncontrada,
    NotaYaExiste,
    Proyecto,
    ProyectoNoExiste,
    ProyectoYaExiste,
    Storage,
    TipoEntrada,
    motivo_omitir_entrada_zip,
    validar_nombre,
    validar_ruta,
)


def get_storage() -> Storage:
    """Factory que devuelve la implementación de Storage según PURPLEMD_STORAGE.

    - "filesystem" (defecto): `FilesystemStorage` usando el directorio de datos.
    - "memory": `MemoryStorage` en RAM (ideal para tests rápidos y efímeros).

    La variable se lee en cada llamada para permitir cambios en caliente
    (útil en tests que monkeypatchean os.environ).
    """
    backend = os.environ.get("PURPLEMD_STORAGE", "filesystem").lower()
    if backend == "memory":
        return MemoryStorage()
    if backend == "filesystem":
        return FilesystemStorage()
    raise ValueError(
        f"PURPLEMD_STORAGE inválido: {backend!r}. Valores válidos: 'filesystem', 'memory'"
    )


__all__ = [
    "Storage",
    "get_storage",
    "FilesystemStorage",
    "MemoryStorage",
    "Proyecto",
    "Entrada",
    "Arbol",
    "Nota",
    "Directorio",
    "NotaError",
    "ProyectoNoExiste",
    "ProyectoYaExiste",
    "NotaNoEncontrada",
    "NotaYaExiste",
    "NombreInvalido",
    "NotaDemasiadoGrande",
    "DirectorioNoEncontrado",
    "DestinoOcupado",
    "DirectorioNoVacio",
    "MovimientoInvalido",
    "MAX_BYTES",
    "MAX_PROFUNDIDAD",
    "MAX_RUTA_BYTES",
    "MAX_IMPORT_ZIP_BYTES",
    "MAX_IMPORT_TOTAL_BYTES",
    "DIR_PROYECTOS",
    "EXTENSION",
    "DIR_DEFECTO",
    "TipoEntrada",
    "validar_nombre",
    "validar_ruta",
    "motivo_omitir_entrada_zip",
]

