"""Protocolo y tipos compartidos para la abstracción de Storage.

Este módulo define el protocolo `Storage` y todos los tipos de datos y excepciones
que necesitan tanto los backends como el núcleo de purplemd. Al estar en un
módulo separado, evita importaciones circulares entre:
- purplemd_storage.__init__ (factory get_storage)
- purplemd_storage.filesystem (FilesystemStorage)
- purplemd_storage.memory (MemoryStorage)
- purplemd.py (núcleo que usa el protocolo)
"""

import zipfile
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

# Constantes públicas
MAX_BYTES = 1_048_576
MAX_PROFUNDIDAD = 10
MAX_RUTA_BYTES = 200
# Un ZIP importado pesa a lo sumo MAX_IMPORT_ZIP_BYTES y en total se
# descomprimen MAX_IMPORT_TOTAL_BYTES (5× el tope de subida: el texto de las
# notas comprime ~3×, con margen). Los dos topes se miran antes de leer.
MAX_IMPORT_ZIP_BYTES = 10 * 1024 * 1024
MAX_IMPORT_TOTAL_BYTES = 50 * 1024 * 1024
DIR_PROYECTOS = "projects"
EXTENSION = ".md"
DIR_DEFECTO = "./local/purplemd"


@runtime_checkable
class Storage(Protocol):
    """Protocolo de almacenamiento: operaciones sobre proyectos y notas.

    Cualquier backend (filesystem, memory, futuro S3, etc.) debe implementar
    estos métodos. Los nombres y firmas coinciden con la API pública de
    `purplemd.py` para que la refactorización sea mecánica.
    """

    def listar_proyectos(self) -> list["Proyecto"]:
        """Lista proyectos ordenados por modificación descendente."""

    def crear_proyecto(self, name: str) -> "Proyecto":
        """Crea un proyecto; lanza ProyectoYaExiste si ya hay uno."""

    def renombrar_proyecto(self, name: str, nuevo: str) -> "Proyecto":
        """Renombra un proyecto; idempotente si el nombre es igual."""

    def eliminar_proyecto(self, name: str) -> None:
        """Borra un proyecto recursivamente."""

    def arbol_proyecto(self, proyecto: str) -> "Arbol":
        """Devuelve el árbol recursivo del proyecto."""

    def leer_nota(self, proyecto: str, ruta: str) -> "Nota":
        """Lee una nota completa."""

    def crear_nota(self, proyecto: str, ruta: str, content: str) -> "Nota":
        """Crea una nota; lanza NotaYaExiste si ya existe."""

    def guardar_nota(self, proyecto: str, ruta: str, content: str) -> "Nota":
        """Reemplaza el contenido de una nota existente."""

    def renombrar_nota(self, proyecto: str, ruta: str, nuevo: str) -> "Nota":
        """Renombra una nota en su misma carpeta."""

    def mover_nota(self, proyecto: str, ruta: str, destino: str) -> "Nota":
        """Mueve o renombra una nota a otra ruta del mismo proyecto."""

    def eliminar_nota(self, proyecto: str, ruta: str) -> None:
        """Borra una nota."""

    def renombrar_directorio(self, proyecto: str, ruta: str, nuevo: str) -> "Directorio":
        """Renombra un directorio en su misma carpeta."""

    def mover_directorio(self, proyecto: str, ruta: str, destino: str) -> "Directorio":
        """Mueve o renombra un directorio con su contenido."""

    def eliminar_directorio(self, proyecto: str, ruta: str, recursive: bool = False) -> None:
        """Borra un directorio; con recursive borra todo su contenido."""

    def esta_operativo(self) -> bool:
        """Indica si el backend está disponible y escribible."""

    def exportar_proyecto(self, proyecto: str) -> bytes:
        """Exporta un proyecto completo como bytes ZIP.

        El ZIP contiene:
        - .purplemd.json: metadata (project, exported_at, version)
        - Archivos .md con la estructura de carpetas preservada
        """

    def importar_proyecto(self, proyecto: str, zip_bytes: bytes) -> dict:
        """Importa un proyecto desde bytes ZIP.

        Devuelve dict con: {"creadas": int, "actualizadas": int,
        "omitidas": int, "errores": list[dict]}
        """


@dataclass(frozen=True)
class Proyecto:
    """Un proyecto con su fecha de modificación (epoch)."""

    name: str
    modified: float


TipoEntrada = Literal["dir", "note"]


@dataclass(frozen=True)
class Entrada:
    """Entrada del árbol: subcarpeta o nota."""

    type: TipoEntrada
    path: str
    modified: float


@dataclass(frozen=True)
class Arbol:
    """Árbol completo de un proyecto."""

    project: str
    entries: list[Entrada]


@dataclass(frozen=True)
class Nota:
    """Una nota con contenido y modificación."""

    project: str
    path: str
    content: str
    modified: float


@dataclass(frozen=True)
class Directorio:
    """Un directorio dentro de un proyecto."""

    project: str
    path: str
    modified: float


# Excepciones
class NotaError(Exception):
    """Base de los errores del almacenamiento."""


class ProyectoNoExiste(NotaError):  # noqa: N818
    """No hay ningún proyecto con ese nombre."""


class ProyectoYaExiste(NotaError):  # noqa: N818
    """Ya hay un proyecto con ese nombre."""


class NotaNoEncontrada(NotaError):  # noqa: N818
    """No existe ninguna nota con esa ruta en ese proyecto."""


class NotaYaExiste(NotaError):  # noqa: N818
    """Ya hay una nota con esa ruta."""


class NombreInvalido(NotaError):  # noqa: N818
    """El nombre de proyecto o la ruta de nota no son seguros ni usables."""


class NotaDemasiadoGrande(NotaError):  # noqa: N818
    """El contenido supera MAX_BYTES."""


class DirectorioNoEncontrado(NotaError):  # noqa: N818
    """No existe ningún directorio con esa ruta en ese proyecto."""


class DestinoOcupado(NotaError):  # noqa: N818
    """Ya hay una nota o un directorio en la ruta destino."""


class DirectorioNoVacio(NotaError):  # noqa: N818
    """El directorio tiene contenido y no se pidió borrado recursivo."""


class MovimientoInvalido(NotaError):  # noqa: N818
    """Un directorio no puede moverse dentro de sí mismo ni hacia un ancestro propio."""


__all__ = [
    "Storage",
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


def validar_nombre(name: str) -> str:
    """Valida un nombre lógico (de proyecto o segmento de ruta) sin extensión.

    Rechaza vacío, separadores de ruta (`/` y `\\`), cualquier `..`,
    nombres que empiecen con `.` (incluye los archivos ocultos del sistema)
    y todo carácter fuera de letras, dígitos, espacio, `_` y `-`. Las letras
    y dígitos son los de `str.isalnum`, así que admiten tildes y `ñ`:
    "índice de compras" es un nombre válido.
    """
    nombre = name[:-3] if name.lower().endswith(EXTENSION) else name
    if not nombre.strip():
        raise NombreInvalido("el nombre no puede estar vacío")
    if "/" in nombre or "\\" in nombre:
        raise NombreInvalido(f"el nombre {name!r} no puede contener separadores de ruta")
    if ".." in nombre:
        raise NombreInvalido(f"el nombre {name!r} no puede contener '..'")
    if nombre.startswith("."):
        raise NombreInvalido(f"el nombre {name!r} no puede empezar con '.'")
    invalidos = sorted({char for char in nombre if not (char.isalnum() or char in " -_")})
    if invalidos:
        raise NombreInvalido(
            f"el nombre {name!r} contiene caracteres no permitidos: {''.join(invalidos)}"
        )
    return nombre


def validar_ruta(ruta: str) -> str:
    r"""Valida la ruta lógica de una nota dentro de un proyecto.

    La ruta se parte por `/` y cada segmento pasa por `validar_nombre`, con
    lo que se rechazan `.` y `..` (también como segmento intermedio),
    segmentos vacíos (`a//b`), barras inicial o final y `\`. Además acota la
    profundidad a MAX_PROFUNDIDAD segmentos y la longitud a MAX_RUTA_BYTES
    bytes. Devuelve la ruta normalizada, sin extensión `.md`.
    """
    sin_extension = ruta[:-3] if ruta.lower().endswith(EXTENSION) else ruta
    if not sin_extension.strip():
        raise NombreInvalido("la ruta de la nota no puede estar vacía")
    if sin_extension.startswith("/") or sin_extension.endswith("/"):
        raise NombreInvalido(f"la ruta {ruta!r} no puede empezar ni terminar con '/'")
    if len(sin_extension.encode("utf-8")) > MAX_RUTA_BYTES:
        raise NombreInvalido(
            f"la ruta {ruta!r} supera los {MAX_RUTA_BYTES} bytes permitidos"
        )
    segmentos = sin_extension.split("/")
    if len(segmentos) > MAX_PROFUNDIDAD:
        raise NombreInvalido(
            f"la ruta {ruta!r} supera los {MAX_PROFUNDIDAD} niveles permitidos"
        )
    partes = []
    for segmento in segmentos:
        if not segmento.strip():
            raise NombreInvalido(f"la ruta {ruta!r} tiene segmentos vacíos")
        try:
            partes.append(validar_nombre(segmento))
        except NombreInvalido as exc:
            raise NombreInvalido(f"la ruta {ruta!r} es inválida: {exc}") from exc
    return "/".join(partes)


def motivo_omitir_entrada_zip(zip_info: zipfile.ZipInfo, acumulado: int) -> str | None:
    """Motivo para descartar una entrada del ZIP antes de descomprimir, o None.

    La decisión se toma sobre `file_size` (central directory) y **antes** de
    `zf.read()`: leer primero y medir después ya habría costado la memoria,
    que es justo lo que busca una zip bomb. `acumulado` es la suma de
    `file_size` de las entradas ya aceptadas y acota el total que puede
    descomprimir un solo ZIP. Para `.purplemd.json` se llama con `acumulado=0`.
    """
    if zip_info.file_size > MAX_BYTES:
        return f"supera {MAX_BYTES} bytes ({zip_info.file_size})"
    if acumulado + zip_info.file_size > MAX_IMPORT_TOTAL_BYTES:
        return f"el ZIP supera los {MAX_IMPORT_TOTAL_BYTES} bytes descomprimidos"
    return None

