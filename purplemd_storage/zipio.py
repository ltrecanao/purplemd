"""Lectura y validación de los ZIP de export, común a todos los backends.

El ZIP lo escribe `FilesystemStorage.exportar_proyecto`, pero *validarlo*
es el mismo trabajo en cualquier backend: qué entradas son `.md`, si sus
rutas pasan la validación y si respetan los topes de tamaño. Esa lógica
vive acá para que `FilesystemStorage` y `DriveStorage` no puedan
divergir: `ContratoBackendsTests` compara las respuestas de ambos, y
este módulo es lo que las mantiene iguales.

Los topes se aplican **antes** de descomprimir (`motivo_omitir_entrada_zip`
lee `file_size` del central directory): `zf.read()` sobre una entrada
gigante ya habría gastado la memoria.
"""

import json
import zipfile
from dataclasses import dataclass, field
from io import BytesIO

from purplemd_storage.protocol import (
    EXTENSION,
    MAX_BYTES,
    NombreInvalido,
    motivo_omitir_entrada_zip,
    validar_ruta,
)

# Metadata que todo export válido lleva en la raíz del ZIP.
ARCHIVO_META = ".purplemd.json"


def _resultado_vacio() -> dict:
    """Contadores en cero.

    `creadas` y `actualizadas` arrancan en 0 porque quién decide eso es
    el backend: solo él sabe si la nota ya existía en su storage.
    """
    return {"creadas": 0, "actualizadas": 0, "omitidas": 0, "errores": []}


@dataclass
class LecturaZip:
    """Lo que el ZIP trae, separado de cómo cada backend lo persiste."""

    notas: list[tuple[str, str]] = field(default_factory=list)
    """Pares `(ruta lógica, contenido)` ya validados, listos para escribir."""

    resultado: dict = field(default_factory=_resultado_vacio)
    """Contadores acumulados: omitidas, errores y los que vaya sumando el backend."""

    abortar: bool = False
    """True si el ZIP no llegó a validarse: no hay nada que escribir."""


def _validar_meta(zf: zipfile.ZipFile, resultado: dict) -> bool:
    """Revisa `.purplemd.json`; `False` si el ZIP no es un export válido."""
    try:
        info = zf.getinfo(ARCHIVO_META)
        # El tamaño declarado se mira antes de leerla: una entrada gigante
        # hecha pasar por `.purplemd.json` es otra zip bomb.
        motivo = motivo_omitir_entrada_zip(info, 0)
        if motivo:
            resultado["errores"].append({"path": ARCHIVO_META, "motivo": motivo})
            return False
        meta = json.loads(zf.read(ARCHIVO_META).decode("utf-8"))
        if meta.get("version") != 1:
            resultado["errores"].append({
                "path": ARCHIVO_META,
                "motivo": f"versión de export no compatible: {meta.get('version')}",
            })
            return False
    except (KeyError, json.JSONDecodeError):
        resultado["errores"].append({
            "path": ARCHIVO_META,
            "motivo": "ZIP inválido: falta o corrupto .purplemd.json",
        })
        return False
    return True


def _leer_entradas(zf: zipfile.ZipFile, resultado: dict) -> list[tuple[str, str]]:
    """Devuelve las entradas `.md` aptas; el resto queda en `resultado`."""
    notas: list[tuple[str, str]] = []
    descomprimido = 0
    for zip_info in zf.infolist():
        if zip_info.filename == ARCHIVO_META:
            continue
        if not zip_info.filename.endswith(EXTENSION):
            resultado["omitidas"] += 1
            resultado["errores"].append({
                "path": zip_info.filename,
                "motivo": "no es un archivo .md",
            })
            continue

        ruta_logica = zip_info.filename[: -len(EXTENSION)]
        try:
            validar_ruta(ruta_logica)

            # Tope antes de descomprimir: `zf.read()` sobre una entrada
            # gigante ya habría gastado la memoria.
            motivo = motivo_omitir_entrada_zip(zip_info, descomprimido)
            if motivo:
                resultado["omitidas"] += 1
                resultado["errores"].append({"path": ruta_logica, "motivo": motivo})
                continue
            descomprimido += zip_info.file_size

            contenido = zf.read(zip_info.filename).decode("utf-8")

            tamano = len(contenido.encode("utf-8"))
            if tamano > MAX_BYTES:
                resultado["omitidas"] += 1
                resultado["errores"].append({
                    "path": ruta_logica,
                    "motivo": f"supera {MAX_BYTES} bytes ({tamano})",
                })
                continue

        except NombreInvalido as exc:
            resultado["omitidas"] += 1
            resultado["errores"].append({"path": ruta_logica, "motivo": str(exc)})
            continue
        except UnicodeDecodeError:
            resultado["omitidas"] += 1
            resultado["errores"].append({"path": ruta_logica, "motivo": "no es UTF-8 válido"})
            continue
        except Exception as exc:  # CRC roto u otro fallo de descompresión
            resultado["omitidas"] += 1
            resultado["errores"].append({
                "path": ruta_logica,
                "motivo": f"error interno: {exc}",
            })
            continue

        notas.append((ruta_logica, contenido))
    return notas


def leer_notas_zip(zip_bytes: bytes) -> LecturaZip:
    """Valida un ZIP de export y devuelve las notas listas para escribir.

    Un ZIP corrupto, sin metadata o con versión incompatible no aborta
    con una excepción: devuelve `abortar=True` y el motivo en
    `resultado["errores"]`, para que la API responda 200 con el detalle
    (que es como siempre respondió el import).
    """
    lectura = LecturaZip()
    try:
        with zipfile.ZipFile(BytesIO(zip_bytes), "r") as zf:
            if not _validar_meta(zf, lectura.resultado):
                lectura.abortar = True
                return lectura
            lectura.notas = _leer_entradas(zf, lectura.resultado)
    except zipfile.BadZipFile:
        lectura.resultado["errores"].append({
            "path": "zip",
            "motivo": "archivo ZIP corrupto o inválido",
        })
        lectura.abortar = True
    return lectura
