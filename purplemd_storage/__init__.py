"""Abstracción de almacenamiento para PurpleMD.

Define el protocolo `Storage` y la factory `get_storage()` que selecciona el
backend según la variable de entorno `PURPLEMD_STORAGE` (valores: "filesystem",
"memory" o "drive"). Por defecto usa "filesystem".
"""

import os

from purplemd_storage.drive import (
    ClienteDrive,
    DriveStorage,
    ErrorDrive,
    NoEncontradoEnDrive,
    TokenVencido,
)
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
    - "drive": **no** se puede construir acá. El storage de Drive pertenece a
      una cuenta de Google concreta, así que se arma por request en `api.py`
      a partir de la sesión. Este error es intencional: un caller sin sesión
      (el servidor MCP, `purplemd` sin `storage=`) tiene que saber que no
      puede tocar los datos.

    La variable se lee en cada llamada para permitir cambios en caliente
    (útil en tests que monkeypatchean os.environ).
    """
    backend = os.environ.get("PURPLEMD_STORAGE", "filesystem").lower()
    if backend == "memory":
        return MemoryStorage()
    if backend == "filesystem":
        return FilesystemStorage()
    if backend == "drive":
        raise ValueError(
            "PURPLEMD_STORAGE=drive necesita una sesión de Google: el storage se "
            "construye por request desde la API, no con get_storage()"
        )
    raise ValueError(
        f"PURPLEMD_STORAGE inválido: {backend!r}. Valores válidos: "
        "'filesystem', 'memory', 'drive'"
    )


__all__ = [
    "Storage",
    "get_storage",
    "FilesystemStorage",
    "MemoryStorage",
    "DriveStorage",
    "ClienteDrive",
    "ErrorDrive",
    "TokenVencido",
    "NoEncontradoEnDrive",
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

