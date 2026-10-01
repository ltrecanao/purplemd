"""Backend de almacenamiento en sistema de archivos para PurpleMD.

Implementa el protocolo `Storage` delegando todas las operaciones a disco.
Es la implementación original movida desde `purplemd.py` para que el núcleo
dependa solo del protocolo y no de `pathlib`, `os`, `shutil` ni `tempfile`.
"""

import json
import os
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from purplemd_storage.protocol import (
    DIR_PROYECTOS,
    EXTENSION,
    MAX_BYTES,
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
    validar_nombre,
    validar_ruta,
)

DIR_DEFECTO = "./local/purplemd"


class FilesystemStorage:
    """Implementación de Storage sobre disco local.

    Mantiene toda la lógica de persistencia original: escrituras atómicas,
    validaciones de path traversal, límites de profundidad y tamaño,
    renombres/movimientos atómicos con `Path.replace`.
    """

    def __init__(self, directorio: Path | None = None) -> None:
        """Inicializa el backend.

        Args:
            directorio: Directorio de datos explícito (inyectado en tests).
                        Si es None, se resuelve desde PURPLEMD_DIR en cada
                        operación para que cambios en el entorno surtan efecto.
        """
        self._directorio_inyectado = directorio

    # --- Utilidades internas ---

    def _directorio_entorno(self) -> Path:
        """Directorio indicado por PURPLEMD_DIR, o DIR_DEFECTO si no está."""
        return Path(os.environ.get("PURPLEMD_DIR", DIR_DEFECTO))

    def _directorio_datos(self) -> Path:
        """Resuelve el directorio de datos y lo crea si no existe."""
        if self._directorio_inyectado is not None:
            ruta = self._directorio_inyectado
        else:
            ruta = self._directorio_entorno()
        ruta.mkdir(parents=True, exist_ok=True)
        return ruta

    def _directorio_proyectos(self) -> Path:
        """Carpeta `projects/` del directorio de datos."""
        return self._directorio_datos() / DIR_PROYECTOS

    def _ruta_proyecto(self, nombre: str) -> Path:
        """Ruta del directorio de un proyecto ya validado."""
        return self._directorio_proyectos() / nombre

    def _verificar_proyecto(self, ruta: Path, nombre: str) -> None:
        """Lanza ProyectoNoExiste si falta el directorio del proyecto."""
        if not ruta.is_dir():
            raise ProyectoNoExiste(f"no existe el proyecto {nombre!r}")

    def _ruta_nota(self, nombre: str, logica: str) -> Path:
        """Ruta completa de una nota ya validada, dentro de un proyecto existente."""
        proyecto = self._ruta_proyecto(nombre)
        self._verificar_proyecto(proyecto, nombre)
        return proyecto / f"{logica}{EXTENSION}"

    def _ruta_directorio(self, nombre: str, logica: str) -> Path:
        """Ruta completa de un directorio ya validado, dentro de un proyecto existente."""
        proyecto = self._ruta_proyecto(nombre)
        self._verificar_proyecto(proyecto, nombre)
        return proyecto / logica

    def _verificar_tamano(self, content: str) -> None:
        """Rechaza contenido por encima de MAX_BYTES antes de tocar el disco."""
        tamano = len(content.encode("utf-8"))
        if tamano > MAX_BYTES:
            raise NotaDemasiadoGrande(f"la nota ocupa {tamano} bytes y el máximo es {MAX_BYTES}")

    def _escribir_atomico(self, ruta: Path, content: str) -> None:
        """Escribe la nota de forma atómica para no dejar archivos a medias.

        El temporal vive en el mismo directorio (para que `replace` sea un rename
        y no un cruce de filesystems) y lleva sufijo `.tmp` para que nunca lo
        capture el árbol del proyecto. Si la escritura falla, el temporal se
        borra y la nota original queda intacta.
        """
        descriptor, temporal = tempfile.mkstemp(dir=ruta.parent, prefix=".", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as archivo:
                archivo.write(content)
                archivo.flush()
                os.fsync(archivo.fileno())
            Path(temporal).replace(ruta)
        except BaseException:
            Path(temporal).unlink(missing_ok=True)
            raise

    def _nombre_usable(self, nombre: str) -> bool:
        """¿Pasa la validación de nombres? Para listar se omite lo que no pase."""
        try:
            validar_nombre(nombre)
        except NombreInvalido:
            return False
        return True

    def _recorrer(
        self, base: Path, actual: Path, carpetas: list[Entrada], notas: list[Entrada]
    ) -> None:
        """Junta carpetas y notas de `actual` (y sus subcarpetas) en dos listas."""
        for hijo in actual.iterdir():
            relativa = hijo.relative_to(base).as_posix()
            if hijo.is_dir():
                if not self._nombre_usable(hijo.name):
                    continue
                carpetas.append(
                    Entrada(type="dir", path=relativa, modified=hijo.stat().st_mtime)
                )
                self._recorrer(base, hijo, carpetas, notas)
            elif hijo.is_file() and hijo.suffix == EXTENSION and self._nombre_usable(hijo.stem):
                notas.append(
                    Entrada(
                        type="note",
                        path=relativa.removesuffix(EXTENSION),
                        modified=hijo.stat().st_mtime,
                    )
                )

    def _mismo_directorio(self, ruta: str, nombre: str) -> str:
        """Ruta resultante de cambiar solo el último segmento de `ruta`."""
        padre, _, _ = ruta.rpartition("/")
        return f"{padre}/{nombre}" if padre else nombre

    def _dentro_de(self, ruta: str, carpeta: str) -> bool:
        """¿`ruta` está dentro de `carpeta`, sin incluir la igualdad?"""
        return ruta.startswith(f"{carpeta}/")

    # --- Implementación del protocolo Storage ---

    def listar_proyectos(self) -> list[Proyecto]:
        """Lista los proyectos del directorio `projects/`, más recientes primero."""
        base = self._directorio_proyectos()
        if not base.is_dir():
            return []
        proyectos = []
        for ruta in base.iterdir():
            if not ruta.is_dir():
                continue
            try:
                nombre = validar_nombre(ruta.name)
            except NombreInvalido:
                continue
            proyectos.append(Proyecto(name=nombre, modified=ruta.stat().st_mtime))
        proyectos.sort(key=lambda proyecto: proyecto.modified, reverse=True)
        return proyectos

    def crear_proyecto(self, name: str) -> Proyecto:
        """Crea el directorio del proyecto; lanza ProyectoYaExiste si ya hay uno."""
        nombre = validar_nombre(name)
        ruta = self._ruta_proyecto(nombre)
        try:
            ruta.mkdir(parents=True)
        except FileExistsError as exc:
            raise ProyectoYaExiste(f"ya existe el proyecto {nombre!r}") from exc
        return Proyecto(name=nombre, modified=ruta.stat().st_mtime)

    def renombrar_proyecto(self, name: str, nuevo: str) -> Proyecto:
        """Cambia el nombre de un proyecto sin tocar su contenido."""
        nombre = validar_nombre(name)
        nuevo_nombre = validar_nombre(nuevo)
        ruta = self._ruta_proyecto(nombre)
        self._verificar_proyecto(ruta, nombre)
        if nuevo_nombre == nombre:
            return Proyecto(name=nombre, modified=ruta.stat().st_mtime)
        destino = self._ruta_proyecto(nuevo_nombre)
        if destino.exists():
            raise ProyectoYaExiste(f"ya existe el proyecto {nuevo_nombre!r}")
        ruta.replace(destino)
        return Proyecto(name=nuevo_nombre, modified=destino.stat().st_mtime)

    def eliminar_proyecto(self, name: str) -> None:
        """Borra el proyecto con todo su contenido, de forma recursiva."""
        nombre = validar_nombre(name)
        ruta = self._ruta_proyecto(nombre)
        self._verificar_proyecto(ruta, nombre)
        shutil.rmtree(ruta)

    def arbol_proyecto(self, proyecto: str) -> Arbol:
        """Árbol recursivo de un proyecto: carpetas alfabéticas y después notas."""
        nombre = validar_nombre(proyecto)
        ruta = self._ruta_proyecto(nombre)
        self._verificar_proyecto(ruta, nombre)
        carpetas: list[Entrada] = []
        notas: list[Entrada] = []
        self._recorrer(ruta, ruta, carpetas, notas)
        carpetas.sort(key=lambda entrada: entrada.path)
        notas.sort(key=lambda entrada: entrada.path)
        return Arbol(project=nombre, entries=[*carpetas, *notas])

    def leer_nota(self, proyecto: str, ruta: str) -> Nota:
        """Lee una nota completa; lanza ProyectoNoExiste o NotaNoEncontrada."""
        nombre = validar_nombre(proyecto)
        logica = validar_ruta(ruta)
        destino = self._ruta_nota(nombre, logica)
        if not destino.is_file():
            raise NotaNoEncontrada(f"no existe la nota {logica!r} en el proyecto {nombre!r}")
        contenido = destino.read_text(encoding="utf-8")
        return Nota(
            project=nombre,
            path=logica,
            content=contenido,
            modified=destino.stat().st_mtime,
        )

    def crear_nota(self, proyecto: str, ruta: str, content: str) -> Nota:
        """Crea una nota; lanza NotaYaExiste si ya hay una en esa ruta."""
        nombre = validar_nombre(proyecto)
        logica = validar_ruta(ruta)
        self._verificar_tamano(content)
        destino = self._ruta_nota(nombre, logica)
        if destino.exists():
            raise NotaYaExiste(f"ya existe la nota {logica!r} en el proyecto {nombre!r}")
        destino.parent.mkdir(parents=True, exist_ok=True)
        self._escribir_atomico(destino, content)
        return Nota(
            project=nombre, path=logica, content=content, modified=destino.stat().st_mtime
        )

    def guardar_nota(self, proyecto: str, ruta: str, content: str) -> Nota:
        """Reemplaza el contenido de una nota existente; lanza NotaNoEncontrada."""
        nombre = validar_nombre(proyecto)
        logica = validar_ruta(ruta)
        self._verificar_tamano(content)
        destino = self._ruta_nota(nombre, logica)
        if not destino.is_file():
            raise NotaNoEncontrada(f"no existe la nota {logica!r} en el proyecto {nombre!r}")
        self._escribir_atomico(destino, content)
        return Nota(
            project=nombre, path=logica, content=content, modified=destino.stat().st_mtime
        )

    def renombrar_nota(self, proyecto: str, ruta: str, nuevo: str) -> Nota:
        """Cambia solo el nombre de una nota, dejándola en su misma carpeta."""
        logica = validar_ruta(ruta)
        segmento = validar_nombre(nuevo)
        return self.mover_nota(proyecto, logica, self._mismo_directorio(logica, segmento))

    def mover_nota(self, proyecto: str, ruta: str, destino: str) -> Nota:
        """Mueve o renombra una nota a otra ruta relativa del mismo proyecto."""
        nombre = validar_nombre(proyecto)
        origen_logica = validar_ruta(ruta)
        destino_logica = validar_ruta(destino)
        origen = self._ruta_nota(nombre, origen_logica)
        if not origen.is_file():
            raise NotaNoEncontrada(
                f"no existe la nota {origen_logica!r} en el proyecto {nombre!r}"
            )
        if destino_logica == origen_logica:
            contenido = origen.read_text(encoding="utf-8")
            return Nota(
                project=nombre,
                path=origen_logica,
                content=contenido,
                modified=origen.stat().st_mtime,
            )
        destino_ruta = self._ruta_nota(nombre, destino_logica)
        if destino_ruta.exists():
            raise DestinoOcupado(f"ya existe una nota en la ruta destino {destino_logica!r}")
        destino_ruta.parent.mkdir(parents=True, exist_ok=True)
        origen.replace(destino_ruta)
        contenido = destino_ruta.read_text(encoding="utf-8")
        return Nota(
            project=nombre,
            path=destino_logica,
            content=contenido,
            modified=destino_ruta.stat().st_mtime,
        )

    def eliminar_nota(self, proyecto: str, ruta: str) -> None:
        """Borra una nota (solo el archivo); lanza ProyectoNoExiste o NotaNoEncontrada."""
        nombre = validar_nombre(proyecto)
        logica = validar_ruta(ruta)
        destino = self._ruta_nota(nombre, logica)
        if not destino.is_file():
            raise NotaNoEncontrada(f"no existe la nota {logica!r} en el proyecto {nombre!r}")
        destino.unlink()

    def renombrar_directorio(self, proyecto: str, ruta: str, nuevo: str) -> Directorio:
        """Cambia solo el nombre de un directorio, dejándolo en su misma carpeta."""
        logica = validar_ruta(ruta)
        segmento = validar_nombre(nuevo)
        return self.mover_directorio(proyecto, logica, self._mismo_directorio(logica, segmento))

    def mover_directorio(self, proyecto: str, ruta: str, destino: str) -> Directorio:
        """Mueve o renombra un directorio (con todo su contenido) dentro del proyecto."""
        nombre = validar_nombre(proyecto)
        origen_logica = validar_ruta(ruta)
        destino_logica = validar_ruta(destino)
        origen = self._ruta_directorio(nombre, origen_logica)
        if not origen.is_dir():
            raise DirectorioNoEncontrado(
                f"no existe el directorio {origen_logica!r} en el proyecto {nombre!r}"
            )
        if destino_logica == origen_logica:
            return Directorio(
                project=nombre, path=origen_logica, modified=origen.stat().st_mtime
            )
        dentro = self._dentro_de(destino_logica, origen_logica) or self._dentro_de(
            origen_logica, destino_logica
        )
        if dentro:
            raise MovimientoInvalido(
                f"no se puede mover el directorio {origen_logica!r} hacia {destino_logica!r}: "
                "una ruta contiene a la otra"
            )
        destino_ruta = self._ruta_directorio(nombre, destino_logica)
        if destino_ruta.exists():
            raise DestinoOcupado(
                f"ya existe un directorio en la ruta destino {destino_logica!r}"
            )
        destino_ruta.parent.mkdir(parents=True, exist_ok=True)
        origen.replace(destino_ruta)
        return Directorio(
            project=nombre, path=destino_logica, modified=destino_ruta.stat().st_mtime
        )

    def eliminar_directorio(
        self, proyecto: str, ruta: str, recursive: bool = False
    ) -> None:
        """Borra un directorio del proyecto; con `recursive` borra todo su contenido."""
        nombre = validar_nombre(proyecto)
        logica = validar_ruta(ruta)
        destino = self._ruta_directorio(nombre, logica)
        if not destino.is_dir():
            raise DirectorioNoEncontrado(
                f"no existe el directorio {logica!r} en el proyecto {nombre!r}"
            )
        if recursive:
            shutil.rmtree(destino)
            return
        if any(destino.iterdir()):
            raise DirectorioNoVacio(
                f"el directorio {logica!r} no está vacío; "
                "se necesita recursive=true para borrarlo con todo su contenido"
            )
        destino.rmdir()

    def esta_operativo(self) -> bool:
        """Verifica si el directorio de datos existe y es escribible."""
        try:
            ruta = self._directorio_datos()
        except OSError:
            return False
        return os.access(ruta, os.W_OK)

    def exportar_proyecto(self, proyecto: str) -> bytes:
        """Exporta un proyecto completo como bytes ZIP."""
        nombre = validar_nombre(proyecto)
        ruta_proyecto = self._ruta_proyecto(nombre)
        self._verificar_proyecto(ruta_proyecto, nombre)

        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # Metadata
            meta = {
                "project": nombre,
                "exported_at": datetime.now(UTC).isoformat(),
                "version": 1,
            }
            zf.writestr(".purplemd.json", json.dumps(meta, ensure_ascii=False, indent=2))

            # Recorrer y agregar notas
            arbol = self.arbol_proyecto(nombre)
            for entrada in arbol.entries:
                if entrada.type == "note":
                    ruta_abs = ruta_proyecto / f"{entrada.path}{EXTENSION}"
                    if ruta_abs.is_file():
                        contenido = ruta_abs.read_text(encoding="utf-8")
                        zf.writestr(f"{entrada.path}{EXTENSION}", contenido)
        return buffer.getvalue()

    def importar_proyecto(self, proyecto: str, zip_bytes: bytes) -> dict:
        """Importa un proyecto desde bytes ZIP."""
        nombre = validar_nombre(proyecto)

        # Verificar/crear proyecto
        ruta_proyecto = self._ruta_proyecto(nombre)
        if not ruta_proyecto.exists():
            ruta_proyecto.mkdir(parents=True)

        resultado = {"creadas": 0, "actualizadas": 0, "omitidas": 0, "errores": []}

        try:
            with zipfile.ZipFile(BytesIO(zip_bytes), "r") as zf:
                # Validar metadata
                try:
                    meta_raw = zf.read(".purplemd.json")
                    meta = json.loads(meta_raw.decode("utf-8"))
                    if meta.get("version") != 1:
                        resultado["errores"].append({
                            "path": ".purplemd.json",
                            "motivo": f"versión de export no compatible: {meta.get('version')}"
                        })
                        return resultado
                except (KeyError, json.JSONDecodeError):
                    resultado["errores"].append({
                        "path": ".purplemd.json",
                        "motivo": "ZIP inválido: falta o corrupto .purplemd.json"
                    })
                    return resultado

                # Procesar cada archivo .md
                for zip_info in zf.infolist():
                    if zip_info.filename == ".purplemd.json":
                        continue
                    if not zip_info.filename.endswith(EXTENSION):
                        resultado["omitidas"] += 1
                        resultado["errores"].append({
                            "path": zip_info.filename,
                            "motivo": "no es un archivo .md"
                        })
                        continue

                    ruta_relativa = zip_info.filename[:-3]  # quitar .md
                    try:
                        # Validar ruta
                        validar_ruta(ruta_relativa)

                        contenido = zf.read(zip_info.filename).decode("utf-8")

                        # Verificar tamaño
                        tamano = len(contenido.encode("utf-8"))
                        if tamano > MAX_BYTES:
                            resultado["omitidas"] += 1
                            resultado["errores"].append({
                                "path": ruta_relativa,
                                "motivo": f"supera {MAX_BYTES} bytes ({tamano})"
                            })
                            continue

                        # Crear o actualizar
                        destino = self._ruta_nota(nombre, ruta_relativa)
                        if destino.exists():
                            self._escribir_atomico(destino, contenido)
                            resultado["actualizadas"] += 1
                        else:
                            destino.parent.mkdir(parents=True, exist_ok=True)
                            self._escribir_atomico(destino, contenido)
                            resultado["creadas"] += 1

                    except NombreInvalido as exc:
                        resultado["omitidas"] += 1
                        resultado["errores"].append({
                            "path": ruta_relativa,
                            "motivo": str(exc)
                        })
                    except UnicodeDecodeError:
                        resultado["omitidas"] += 1
                        resultado["errores"].append({
                            "path": ruta_relativa,
                            "motivo": "no es UTF-8 válido"
                        })
                    except Exception as exc:
                        resultado["omitidas"] += 1
                        resultado["errores"].append({
                            "path": ruta_relativa,
                            "motivo": f"error interno: {exc}"
                        })

        except zipfile.BadZipFile:
            resultado["errores"].append({
                "path": "zip",
                "motivo": "archivo ZIP corrupto o inválido"
            })

        return resultado

