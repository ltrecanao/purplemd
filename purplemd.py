"""Núcleo de purplemd: proyectos, notas y persistencia via protocolo Storage.

La lógica de negocio (validaciones, reglas de naming, límites) vive aquí.
La persistencia real se delega a un backend que implementa `Storage`
(filesystem, memory, futuro S3, etc.).

Decisiones no obvias:

- El nombre de proyecto y cada segmento de ruta se validan contra path
  traversal antes de tocar el storage: sin separadores de ruta, sin `..`
  ni puntos iniciales, y solo letras (con tildes y `ñ`), dígitos, espacio,
  `_` y `-`.
- Las rutas se acotan a MAX_PROFUNDIDAD segmentos y MAX_RUTA_BYTES bytes.
  Como cada segmento es más corto que la ruta completa, el tope de bytes
  garantiza además que ningún nombre supere los 255 bytes por archivo que
  admiten los filesystems comunes.
- Las escrituras son atómicas en el backend (temporal + replace en filesystem,
  asignación única en memory) para no dejar notas a medias.
- Renombres, movimientos y borrados trabajan sobre rutas ya validadas, así
  que nunca salen del proyecto: el destino con `..` o absoluto es un error,
  un directorio no puede moverse dentro de sí mismo ni hacia un ancestro
  propio, y los destinos ocupados se rechazan en vez de pisar contenido.
- El backend se resuelve en cada llamada via `get_storage()` para que tests
  puedan inyectar uno distinto (parámetro `storage`) o patchear la variable
  de entorno `PURPLEMD_STORAGE` sin reiniciar el proceso.
- Para compatibilidad hacia atrás, se acepta el parámetro `directorio` (Path)
  que crea un FilesystemStorage con ese directorio.
"""

import os
from pathlib import Path

from purplemd_storage import get_storage
from purplemd_storage.filesystem import FilesystemStorage
from purplemd_storage.protocol import (
    DIR_DEFECTO,
    DIR_PROYECTOS,  # noqa: F401
    EXTENSION,  # noqa: F401
    MAX_BYTES,
    MAX_PROFUNDIDAD,  # noqa: F401
    MAX_RUTA_BYTES,  # noqa: F401
    Arbol,
    DestinoOcupado,  # noqa: F401
    Directorio,
    DirectorioNoEncontrado,  # noqa: F401
    DirectorioNoVacio,  # noqa: F401
    MovimientoInvalido,  # noqa: F401
    NombreInvalido,  # noqa: F401
    Nota,
    NotaDemasiadoGrande,
    NotaError,  # noqa: F401
    NotaNoEncontrada,  # noqa: F401
    NotaYaExiste,  # noqa: F401
    Proyecto,
    ProyectoNoExiste,  # noqa: F401
    ProyectoYaExiste,  # noqa: F401
    Storage,
    validar_nombre,
    validar_ruta,
)


def _directorio_entorno() -> Path:
    """Directorio indicado por PURPLEMD_DIR, o DIR_DEFECTO si no está.

    Mantenido para compatibilidad con tests que acceden a esta función privada.
    """
    return Path(os.environ.get("PURPLEMD_DIR", DIR_DEFECTO))


# Type alias para compatibilidad: storage puede ser Storage o Path (directorio)
StorageOrDirectorio = Storage | Path | None


def _resolve_storage(
    storage: StorageOrDirectorio = None, directorio: StorageOrDirectorio = None
) -> Storage:
    """Resuelve el storage a partir de storage o directorio (compatibilidad).

    - Si `storage` es una instancia de Storage, la devuelve.
    - Si `directorio` es un Path, crea un FilesystemStorage con ese directorio.
    - Si ambos son None, usa get_storage() (lee PURPLEMD_STORAGE).
    - `directorio` tiene prioridad sobre `storage` para compatibilidad con tests.
    """
    # directorio tiene prioridad para compatibilidad hacia atrás
    if directorio is not None:
        if isinstance(directorio, Storage):
            return directorio
        return FilesystemStorage(directorio)
    if storage is not None:
        if isinstance(storage, Storage):
            return storage
        return FilesystemStorage(storage)
    return get_storage()


def _mismo_directorio(ruta: str, nombre: str) -> str:
    """Ruta resultante de cambiar solo el último segmento de `ruta`."""
    padre, _, _ = ruta.rpartition("/")
    return f"{padre}/{nombre}" if padre else nombre


def _dentro_de(ruta: str, carpeta: str) -> bool:
    """¿`ruta` está dentro de `carpeta`, sin incluir la igualdad?"""
    return ruta.startswith(f"{carpeta}/")


# --- Funciones públicas que delegan al Storage ---


def listar_proyectos(
    storage: StorageOrDirectorio = None, directorio: StorageOrDirectorio = None
) -> list[Proyecto]:
    """Lista los proyectos, más recientes primero."""
    storage = _resolve_storage(storage, directorio)
    return storage.listar_proyectos()


def crear_proyecto(
    name: str, storage: StorageOrDirectorio = None, directorio: StorageOrDirectorio = None
) -> Proyecto:
    """Crea un proyecto; lanza ProyectoYaExiste si ya hay uno."""
    storage = _resolve_storage(storage, directorio)
    nombre = validar_nombre(name)
    return storage.crear_proyecto(nombre)


def renombrar_proyecto(
    name: str,
    nuevo: str,
    storage: StorageOrDirectorio = None,
    directorio: StorageOrDirectorio = None,
) -> Proyecto:
    """Cambia el nombre de un proyecto sin tocar su contenido.

    El nombre nuevo pasa por las mismas reglas que al crear. Si ya hay otro
    proyecto con ese nombre lanza ProyectoYaExiste en vez de pisarlo, y si
    es el mismo nombre se resuelve como idempotente: devuelve el proyecto
    tal cual está, sin tocar el storage.
    """
    storage = _resolve_storage(storage, directorio)
    nombre = validar_nombre(name)
    nuevo_nombre = validar_nombre(nuevo)
    return storage.renombrar_proyecto(nombre, nuevo_nombre)


def eliminar_proyecto(
    name: str, storage: StorageOrDirectorio = None, directorio: StorageOrDirectorio = None
) -> None:
    """Borra el proyecto con todo su contenido, de forma recursiva.

    No hay vuelta atrás: la confirmación de la operación es responsabilidad
    de quien llama (el frontend).
    """
    storage = _resolve_storage(storage, directorio)
    nombre = validar_nombre(name)
    storage.eliminar_proyecto(nombre)


def arbol_proyecto(
    proyecto: str, storage: StorageOrDirectorio = None, directorio: StorageOrDirectorio = None
) -> Arbol:
    """Árbol recursivo de un proyecto: carpetas alfabéticas y después notas."""
    storage = _resolve_storage(storage, directorio)
    nombre = validar_nombre(proyecto)
    return storage.arbol_proyecto(nombre)


def leer_nota(
    proyecto: str,
    ruta: str,
    storage: StorageOrDirectorio = None,
    directorio: StorageOrDirectorio = None,
) -> Nota:
    """Lee una nota completa; lanza ProyectoNoExiste o NotaNoEncontrada."""
    storage = _resolve_storage(storage, directorio)
    nombre = validar_nombre(proyecto)
    logica = validar_ruta(ruta)
    return storage.leer_nota(nombre, logica)


def crear_nota(
    proyecto: str,
    ruta: str,
    content: str,
    storage: StorageOrDirectorio = None,
    directorio: StorageOrDirectorio = None,
) -> Nota:
    """Crea una nota; lanza NotaYaExiste si ya hay una en esa ruta.

    Crea las carpetas intermedias que falten dentro del proyecto.
    """
    storage = _resolve_storage(storage, directorio)
    nombre = validar_nombre(proyecto)
    logica = validar_ruta(ruta)
    # Validación de tamaño antes de delegar (regla de negocio)
    tamano = len(content.encode("utf-8"))
    if tamano > MAX_BYTES:
        raise NotaDemasiadoGrande(
            f"la nota ocupa {tamano} bytes y el máximo es {MAX_BYTES}"
        )
    return storage.crear_nota(nombre, logica, content)


def guardar_nota(
    proyecto: str,
    ruta: str,
    content: str,
    storage: StorageOrDirectorio = None,
    directorio: StorageOrDirectorio = None,
) -> Nota:
    """Reemplaza el contenido de una nota existente; lanza NotaNoEncontrada."""
    storage = _resolve_storage(storage, directorio)
    nombre = validar_nombre(proyecto)
    logica = validar_ruta(ruta)
    # Validación de tamaño antes de delegar (regla de negocio)
    tamano = len(content.encode("utf-8"))
    if tamano > MAX_BYTES:
        raise NotaDemasiadoGrande(
            f"la nota ocupa {tamano} bytes y el máximo es {MAX_BYTES}"
        )
    return storage.guardar_nota(nombre, logica, content)


def renombrar_nota(
    proyecto: str,
    ruta: str,
    nuevo: str,
    storage: StorageOrDirectorio = None,
    directorio: StorageOrDirectorio = None,
) -> Nota:
    """Cambia solo el nombre de una nota, dejándola en su misma carpeta.

    Para cambiar de carpeta (o nombre y carpeta a la vez) está mover_nota.
    """
    storage = _resolve_storage(storage, directorio)
    logica = validar_ruta(ruta)
    segmento = validar_nombre(nuevo)
    destino = _mismo_directorio(logica, segmento)
    return storage.mover_nota(proyecto, logica, destino)


def mover_nota(
    proyecto: str,
    ruta: str,
    destino: str,
    storage: StorageOrDirectorio = None,
    directorio: StorageOrDirectorio = None,
) -> Nota:
    """Mueve o renombra una nota a otra ruta relativa del mismo proyecto.

    El destino valida como cualquier ruta de nota, con lo que nunca puede
    salir del proyecto. Crea las carpetas intermedias que falten. Si la
    ruta destino es igual a la origen se resuelve como idempotente (devuelve
    la nota tal cual está) y si ya hay otra nota ahí lanza DestinoOcupado
    sin pisar su contenido.
    """
    storage = _resolve_storage(storage, directorio)
    nombre = validar_nombre(proyecto)
    origen_logica = validar_ruta(ruta)
    destino_logica = validar_ruta(destino)
    return storage.mover_nota(nombre, origen_logica, destino_logica)


def eliminar_nota(
    proyecto: str,
    ruta: str,
    storage: StorageOrDirectorio = None,
    directorio: StorageOrDirectorio = None,
) -> None:
    """Borra una nota (solo el archivo); lanza ProyectoNoExiste o NotaNoEncontrada.

    Las carpetas que queden vacías se conservan: el árbol no cambia de
    forma sorpresiva y quien decide borrar una carpeta es eliminar_directorio.
    """
    storage = _resolve_storage(storage, directorio)
    nombre = validar_nombre(proyecto)
    logica = validar_ruta(ruta)
    storage.eliminar_nota(nombre, logica)


def renombrar_directorio(
    proyecto: str,
    ruta: str,
    nuevo: str,
    storage: StorageOrDirectorio = None,
    directorio: StorageOrDirectorio = None,
) -> Directorio:
    """Cambia solo el nombre de un directorio, dejándolo en su misma carpeta.

    Para cambiar de carpeta (o nombre y carpeta a la vez) está
    mover_directorio.
    """
    storage = _resolve_storage(storage, directorio)
    logica = validar_ruta(ruta)
    segmento = validar_nombre(nuevo)
    destino = _mismo_directorio(logica, segmento)
    return storage.mover_directorio(proyecto, logica, destino)


def mover_directorio(
    proyecto: str,
    ruta: str,
    destino: str,
    storage: StorageOrDirectorio = None,
    directorio: StorageOrDirectorio = None,
) -> Directorio:
    """Mueve o renombra un directorio (con todo su contenido) dentro del proyecto.

    El destino valida como cualquier ruta, así que no puede salir del
    proyecto. Un directorio no puede terminar dentro de sí mismo ni absorber
    a uno de sus ancestros (MovimientoInvalido, 422 en la API); si ya hay
    algo en la ruta destino lanza DestinoOcupado sin pisarlo. Mover a la
    misma ruta es idempotente.
    """
    storage = _resolve_storage(storage, directorio)
    nombre = validar_nombre(proyecto)
    origen_logica = validar_ruta(ruta)
    destino_logica = validar_ruta(destino)
    return storage.mover_directorio(nombre, origen_logica, destino_logica)


def eliminar_directorio(
    proyecto: str,
    ruta: str,
    recursive: bool = False,
    storage: StorageOrDirectorio = None,
    directorio: StorageOrDirectorio = None,
) -> None:
    """Borra un directorio del proyecto; con `recursive` borra todo su contenido.

    Sin `recursive`, si el directorio no está vacío lanza DirectorioNoVacio
    (409 en la API) sin tocar nada: el borrado sin vuelta atrás de contenido
    solo ocurre cuando se pidió explícitamente. La confirmación de ese
    borrado recursivo la hace el frontend.
    """
    storage = _resolve_storage(storage, directorio)
    nombre = validar_nombre(proyecto)
    logica = validar_ruta(ruta)
    storage.eliminar_directorio(nombre, logica, recursive)


def exportar_proyecto(
    proyecto: str,
    storage: StorageOrDirectorio = None,
    directorio: StorageOrDirectorio = None,
) -> bytes:
    """Exporta un proyecto completo como bytes ZIP."""
    storage = _resolve_storage(storage, directorio)
    nombre = validar_nombre(proyecto)
    return storage.exportar_proyecto(nombre)


def importar_proyecto(
    proyecto: str,
    zip_bytes: bytes,
    storage: StorageOrDirectorio = None,
    directorio: StorageOrDirectorio = None,
) -> dict:
    """Importa un proyecto desde bytes ZIP."""
    storage = _resolve_storage(storage, directorio)
    nombre = validar_nombre(proyecto)
    return storage.importar_proyecto(nombre, zip_bytes)

