"""Backend de almacenamiento en memoria (RAM) para PurpleMD.

Implementa el protocolo `Storage` usando un diccionario en memoria.
Ideal para tests rápidos, entornos efímeros y desarrollo sin I/O de disco.

Estructura interna:
    _data: dict[str, ProjectData]
    ProjectData = {
        "modified": float,
        "tree": dict[str, NodeData],
    }
    NodeData = {
        "type": "dir" | "note",
        "content": str | None,  # Solo para notas
        "modified": float,
        "children": set[str],   # Rutas de hijos directos (para directorios)
    }

Las rutas en `tree` son relativas al proyecto, usan `/` como separador,
y NO incluyen la extensión `.md` (ni para notas ni para directorios).
"""

import json
import threading
import time
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from typing import Literal

from purplemd_storage.protocol import (
    MAX_BYTES,
    Arbol,
    DestinoOcupado,
    Directorio,
    DirectorioNoEncontrado,
    DirectorioNoVacio,
    Entrada,
    MovimientoInvalido,
    Nota,
    NotaDemasiadoGrande,
    NotaNoEncontrada,
    NotaYaExiste,
    Proyecto,
    ProyectoNoExiste,
    ProyectoYaExiste,
    motivo_omitir_entrada_zip,
    validar_nombre,
    validar_ruta,
)

TipoEntrada = Literal["dir", "note"]


class MemoryStorage:
    """Implementación de Storage en memoria (thread-safe básico por GIL)."""

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}
        self._lock = threading.RLock()  # Reentrant para llamadas anidadas
        self._contador_modificacion = 0

    def _now(self) -> float:
        """Timestamp monotónico creciente para ordenar modificaciones."""
        with self._lock:
            self._contador_modificacion += 1
            return time.time() + self._contador_modificacion * 1e-9

    def _proyecto_existe(self, nombre: str) -> bool:
        return nombre in self._data

    def _obtener_proyecto(self, nombre: str) -> dict:
        if nombre not in self._data:
            raise ProyectoNoExiste(f"no existe el proyecto {nombre!r}")
        return self._data[nombre]

    def _verificar_tamano(self, content: str) -> None:
        tamano = len(content.encode("utf-8"))
        if tamano > MAX_BYTES:
            raise NotaDemasiadoGrande(f"la nota ocupa {tamano} bytes y el máximo es {MAX_BYTES}")

    def _ruta_padre(self, ruta: str) -> str:
        """Devuelve el directorio padre de una ruta, o '' si está en la raíz."""
        padre, _, _ = ruta.rpartition("/")
        return padre

    def _ruta_existe_en_proyecto(self, proyecto: dict, ruta: str) -> bool:
        return ruta in proyecto["tree"]

    def _es_directorio(self, proyecto: dict, ruta: str) -> bool:
        nodo = proyecto["tree"].get(ruta)
        return nodo is not None and nodo["type"] == "dir"

    def _es_nota(self, proyecto: dict, ruta: str) -> bool:
        nodo = proyecto["tree"].get(ruta)
        return nodo is not None and nodo["type"] == "note"

    def _crear_directorios_intermedios(self, proyecto: dict, ruta: str) -> None:
        """Crea todos los directorios intermedios necesarios para `ruta`."""
        segmentos = ruta.split("/")
        actual = ""
        for segmento in segmentos[:-1]:  # Excluye el último (archivo o dir final)
            actual = f"{actual}/{segmento}" if actual else segmento
            if actual not in proyecto["tree"]:
                proyecto["tree"][actual] = {
                    "type": "dir",
                    "content": None,
                    "modified": self._now(),
                    "children": set(),
                }
            # Actualizar children del padre
            padre = self._ruta_padre(actual)
            if padre:
                proyecto["tree"][padre]["children"].add(actual)
            else:
                # Directorio en la raíz del proyecto
                if "children" not in proyecto:
                    proyecto["children"] = set()
                proyecto["children"].add(actual)

    def _borrar_subarbol(self, proyecto: dict, ruta: str) -> None:
        """Borra recursivamente un directorio y todo su contenido."""
        nodo = proyecto["tree"].get(ruta)
        if not nodo:
            return
        if nodo["type"] == "dir":
            for hijo in list(nodo["children"]):
                self._borrar_subarbol(proyecto, hijo)
        # Eliminar de children del padre
        padre = self._ruta_padre(ruta)
        if padre and padre in proyecto["tree"]:
            proyecto["tree"][padre]["children"].discard(ruta)
        elif not padre and "children" in proyecto:
            proyecto["children"].discard(ruta)
        # Borrar el nodo
        del proyecto["tree"][ruta]

    def _mover_subarbol(self, proyecto: dict, origen: str, destino: str) -> None:
        """Mueve un subárbol (directorio o nota) de origen a destino.

        Asume que origen existe, destino no existe, y no hay conflicto de ancestros.
        """
        nodo = proyecto["tree"].pop(origen)
        # Actualizar children del padre origen
        padre_origen = self._ruta_padre(origen)
        if padre_origen and padre_origen in proyecto["tree"]:
            proyecto["tree"][padre_origen]["children"].discard(origen)
        elif not padre_origen and "children" in proyecto:
            proyecto["children"].discard(origen)

        # Insertar en destino
        proyecto["tree"][destino] = nodo
        nodo["modified"] = self._now()
        # Actualizar children del padre destino
        padre_destino = self._ruta_padre(destino)
        if padre_destino:
            self._crear_directorios_intermedios(proyecto, destino)
            proyecto["tree"][padre_destino]["children"].add(destino)
        else:
            if "children" not in proyecto:
                proyecto["children"] = set()
            proyecto["children"].add(destino)

        # Si es un directorio, actualizar rutas de todos sus descendientes
        if nodo["type"] == "dir":
            self._actualizar_rutas_descendientes(proyecto, origen, destino, nodo)

    def _actualizar_rutas_descendientes(
        self, proyecto: dict, origen: str, destino: str, nodo: dict
    ) -> None:
        """Actualiza recursivamente las rutas de los descendientes tras un movimiento."""
        if nodo["type"] != "dir":
            return
        nuevos_hijos = set()
        for hijo in list(nodo["children"]):
            hijo_nodo = proyecto["tree"].pop(hijo)
            nuevo_hijo = hijo.replace(origen, destino, 1)
            hijo_nodo["modified"] = self._now()
            proyecto["tree"][nuevo_hijo] = hijo_nodo
            nuevos_hijos.add(nuevo_hijo)
            if hijo_nodo["type"] == "dir":
                self._actualizar_rutas_descendientes(proyecto, hijo, nuevo_hijo, hijo_nodo)
        nodo["children"] = nuevos_hijos

    def _listar_arbol(self, proyecto: dict) -> list[Entrada]:
        """Genera la lista de entradas del árbol ordenada: dirs primero, luego notas."""
        carpetas: list[Entrada] = []
        notas: list[Entrada] = []
        for ruta, nodo in proyecto["tree"].items():
            entrada = Entrada(type=nodo["type"], path=ruta, modified=nodo["modified"])
            if nodo["type"] == "dir":
                carpetas.append(entrada)
            else:
                notas.append(entrada)
        carpetas.sort(key=lambda e: e.path)
        notas.sort(key=lambda e: e.path)
        return [*carpetas, *notas]

    # --- Implementación del protocolo Storage ---

    def listar_proyectos(self) -> list[Proyecto]:
        proyectos = []
        for nombre, data in self._data.items():
            proyectos.append(Proyecto(name=nombre, modified=data["modified"]))
        proyectos.sort(key=lambda p: p.modified, reverse=True)
        return proyectos

    def crear_proyecto(self, name: str) -> Proyecto:
        nombre = validar_nombre(name)
        with self._lock:
            if nombre in self._data:
                raise ProyectoYaExiste(f"ya existe el proyecto {nombre!r}")
            now = self._now()
            self._data[nombre] = {
                "modified": now,
                "tree": {},
                "children": set(),
            }
            return Proyecto(name=nombre, modified=now)

    def renombrar_proyecto(self, name: str, nuevo: str) -> Proyecto:
        nombre = validar_nombre(name)
        nuevo_nombre = validar_nombre(nuevo)
        with self._lock:
            if nombre not in self._data:
                raise ProyectoNoExiste(f"no existe el proyecto {nombre!r}")
            if nuevo_nombre == nombre:
                return Proyecto(name=nombre, modified=self._data[nombre]["modified"])
            if nuevo_nombre in self._data:
                raise ProyectoYaExiste(f"ya existe el proyecto {nuevo_nombre!r}")
            # Renombrar: mover datos y borrar clave antigua
            proyecto = self._data.pop(nombre)
            proyecto["modified"] = self._now()
            self._data[nuevo_nombre] = proyecto
            return Proyecto(name=nuevo_nombre, modified=proyecto["modified"])

    def eliminar_proyecto(self, name: str) -> None:
        nombre = validar_nombre(name)
        with self._lock:
            if nombre not in self._data:
                raise ProyectoNoExiste(f"no existe el proyecto {nombre!r}")
            del self._data[nombre]

    def arbol_proyecto(self, proyecto: str) -> Arbol:
        nombre = validar_nombre(proyecto)
        with self._lock:
            data = self._obtener_proyecto(nombre)
            entradas = self._listar_arbol(data)
            return Arbol(project=nombre, entries=entradas)

    def leer_nota(self, proyecto: str, ruta: str) -> Nota:
        nombre = validar_nombre(proyecto)
        logica = validar_ruta(ruta)
        with self._lock:
            data = self._obtener_proyecto(nombre)
            if not self._es_nota(data, logica):
                raise NotaNoEncontrada(f"no existe la nota {logica!r} en el proyecto {nombre!r}")
            nodo = data["tree"][logica]
            return Nota(
                project=nombre,
                path=logica,
                content=nodo["content"] or "",
                modified=nodo["modified"],
            )

    def crear_nota(self, proyecto: str, ruta: str, content: str) -> Nota:
        nombre = validar_nombre(proyecto)
        logica = validar_ruta(ruta)
        self._verificar_tamano(content)
        with self._lock:
            data = self._obtener_proyecto(nombre)
            if self._ruta_existe_en_proyecto(data, logica):
                raise NotaYaExiste(f"ya existe la nota {logica!r} en el proyecto {nombre!r}")
            # Crear directorios intermedios
            self._crear_directorios_intermedios(data, logica)
            now = self._now()
            data["tree"][logica] = {
                "type": "note",
                "content": content,
                "modified": now,
                "children": set(),
            }
            # Actualizar children del padre
            padre = self._ruta_padre(logica)
            if padre:
                data["tree"][padre]["children"].add(logica)
            else:
                data["children"].add(logica)
            return Nota(project=nombre, path=logica, content=content, modified=now)

    def guardar_nota(self, proyecto: str, ruta: str, content: str) -> Nota:
        nombre = validar_nombre(proyecto)
        logica = validar_ruta(ruta)
        self._verificar_tamano(content)
        with self._lock:
            data = self._obtener_proyecto(nombre)
            if not self._es_nota(data, logica):
                raise NotaNoEncontrada(f"no existe la nota {logica!r} en el proyecto {nombre!r}")
            now = self._now()
            data["tree"][logica]["content"] = content
            data["tree"][logica]["modified"] = now
            return Nota(project=nombre, path=logica, content=content, modified=now)

    def renombrar_nota(self, proyecto: str, ruta: str, nuevo: str) -> Nota:
        logica = validar_ruta(ruta)
        segmento = validar_nombre(nuevo)
        padre = self._ruta_padre(logica)
        destino = f"{padre}/{segmento}" if padre else segmento
        return self.mover_nota(proyecto, logica, destino)

    def mover_nota(self, proyecto: str, ruta: str, destino: str) -> Nota:
        nombre = validar_nombre(proyecto)
        origen_logica = validar_ruta(ruta)
        destino_logica = validar_ruta(destino)
        with self._lock:
            data = self._obtener_proyecto(nombre)
            if not self._es_nota(data, origen_logica):
                raise NotaNoEncontrada(
                    f"no existe la nota {origen_logica!r} en el proyecto {nombre!r}"
                )
            if destino_logica == origen_logica:
                nodo = data["tree"][origen_logica]
                return Nota(
                    project=nombre,
                    path=origen_logica,
                    content=nodo["content"] or "",
                    modified=nodo["modified"],
                )
            if self._ruta_existe_en_proyecto(data, destino_logica):
                raise DestinoOcupado(f"ya existe una nota en la ruta destino {destino_logica!r}")
            # Mover la nota
            nodo = data["tree"].pop(origen_logica)
            nodo["modified"] = self._now()
            data["tree"][destino_logica] = nodo
            # Actualizar children
            padre_origen = self._ruta_padre(origen_logica)
            if padre_origen:
                data["tree"][padre_origen]["children"].discard(origen_logica)
            else:
                data["children"].discard(origen_logica)
            self._crear_directorios_intermedios(data, destino_logica)
            padre_destino = self._ruta_padre(destino_logica)
            if padre_destino:
                data["tree"][padre_destino]["children"].add(destino_logica)
            else:
                data["children"].add(destino_logica)
            return Nota(
                project=nombre,
                path=destino_logica,
                content=nodo["content"] or "",
                modified=nodo["modified"],
            )

    def eliminar_nota(self, proyecto: str, ruta: str) -> None:
        nombre = validar_nombre(proyecto)
        logica = validar_ruta(ruta)
        with self._lock:
            data = self._obtener_proyecto(nombre)
            if not self._es_nota(data, logica):
                raise NotaNoEncontrada(f"no existe la nota {logica!r} en el proyecto {nombre!r}")
            # Eliminar de children del padre
            padre = self._ruta_padre(logica)
            if padre:
                data["tree"][padre]["children"].discard(logica)
            else:
                data["children"].discard(logica)
            del data["tree"][logica]

    def renombrar_directorio(self, proyecto: str, ruta: str, nuevo: str) -> Directorio:
        logica = validar_ruta(ruta)
        segmento = validar_nombre(nuevo)
        padre = self._ruta_padre(logica)
        destino = f"{padre}/{segmento}" if padre else segmento
        return self.mover_directorio(proyecto, logica, destino)

    def mover_directorio(self, proyecto: str, ruta: str, destino: str) -> Directorio:
        nombre = validar_nombre(proyecto)
        origen_logica = validar_ruta(ruta)
        destino_logica = validar_ruta(destino)
        with self._lock:
            data = self._obtener_proyecto(nombre)
            if not self._es_directorio(data, origen_logica):
                raise DirectorioNoEncontrado(
                    f"no existe el directorio {origen_logica!r} en el proyecto {nombre!r}"
                )
            if destino_logica == origen_logica:
                nodo = data["tree"][origen_logica]
                return Directorio(
                    project=nombre, path=origen_logica, modified=nodo["modified"]
                )
            # Verificar movimiento inválido (dentro de sí mismo o hacia ancestro)
            dentro = destino_logica.startswith(f"{origen_logica}/") or origen_logica.startswith(
                f"{destino_logica}/"
            )
            if dentro:
                raise MovimientoInvalido(
                    f"no se puede mover el directorio {origen_logica!r} hacia {destino_logica!r}: "
                    "una ruta contiene a la otra"
                )
            if self._ruta_existe_en_proyecto(data, destino_logica):
                raise DestinoOcupado(
                    f"ya existe un directorio en la ruta destino {destino_logica!r}"
                )
            # Mover el subárbol completo
            self._mover_subarbol(data, origen_logica, destino_logica)
            nodo = data["tree"][destino_logica]
            return Directorio(
                project=nombre, path=destino_logica, modified=nodo["modified"]
            )

    def eliminar_directorio(self, proyecto: str, ruta: str, recursive: bool = False) -> None:
        nombre = validar_nombre(proyecto)
        logica = validar_ruta(ruta)
        with self._lock:
            data = self._obtener_proyecto(nombre)
            if not self._es_directorio(data, logica):
                raise DirectorioNoEncontrado(
                    f"no existe el directorio {logica!r} en el proyecto {nombre!r}"
                )
            if not recursive:
                nodo = data["tree"][logica]
                if nodo["children"]:
                    raise DirectorioNoVacio(
                        f"el directorio {logica!r} no está vacío; "
                        "se necesita recursive=true para borrarlo con todo su contenido"
                    )
            self._borrar_subarbol(data, logica)

    def esta_operativo(self) -> bool:
        """El backend en memoria siempre está operativo."""
        return True

    def exportar_proyecto(self, proyecto: str) -> bytes:
        """Exporta un proyecto completo como bytes ZIP."""
        nombre = validar_nombre(proyecto)
        with self._lock:
            data = self._obtener_proyecto(nombre)

            buffer = BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                # Metadata
                meta = {
                    "project": nombre,
                    "exported_at": datetime.now(UTC).isoformat(),
                    "version": 1,
                }
                zf.writestr(".purplemd.json", json.dumps(meta, ensure_ascii=False, indent=2))

                # Agregar notas
                for ruta, nodo in data["tree"].items():
                    if nodo["type"] == "note":
                        contenido = nodo["content"] or ""
                        zf.writestr(f"{ruta}.md", contenido)
            return buffer.getvalue()

    def importar_proyecto(self, proyecto: str, zip_bytes: bytes) -> dict:
        """Importa un proyecto desde bytes ZIP."""
        nombre = validar_nombre(proyecto)

        with self._lock:
            # Verificar/crear proyecto
            if nombre not in self._data:
                self._data[nombre] = {
                    "modified": self._now(),
                    "tree": {},
                    "children": set(),
                }
            data = self._data[nombre]

            resultado = {"creadas": 0, "actualizadas": 0, "omitidas": 0, "errores": []}

            try:
                with zipfile.ZipFile(BytesIO(zip_bytes), "r") as zf:
                    # Validar metadata. El tamaño declarado se mira antes de
                    # leerla: una entrada gigante hecha pasar por
                    # `.purplemd.json` es otra zip bomb, y esta se descomprime
                    # antes del bucle.
                    try:
                        info_meta = zf.getinfo(".purplemd.json")
                        meta_motivo = motivo_omitir_entrada_zip(info_meta, 0)
                        if meta_motivo:
                            resultado["errores"].append({
                                "path": ".purplemd.json",
                                "motivo": meta_motivo
                            })
                            return resultado
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
                    descomprimido = 0
                    for zip_info in zf.infolist():
                        if zip_info.filename == ".purplemd.json":
                            continue
                        if not zip_info.filename.endswith(".md"):
                            resultado["omitidas"] += 1
                            resultado["errores"].append({
                                "path": zip_info.filename,
                                "motivo": "no es un archivo .md"
                            })
                            continue

                        ruta_relativa = zip_info.filename[:-3]  # quitar .md
                        try:
                            validar_ruta(ruta_relativa)

                            # Tope antes de descomprimir: `zf.read()` sobre
                            # una entrada gigante ya habría gastado la memoria.
                            motivo = motivo_omitir_entrada_zip(zip_info, descomprimido)
                            if motivo:
                                resultado["omitidas"] += 1
                                resultado["errores"].append({
                                    "path": ruta_relativa,
                                    "motivo": motivo
                                })
                                continue
                            descomprimido += zip_info.file_size

                            contenido = zf.read(zip_info.filename).decode("utf-8")

                            tamano = len(contenido.encode("utf-8"))
                            if tamano > MAX_BYTES:
                                resultado["omitidas"] += 1
                                resultado["errores"].append({
                                    "path": ruta_relativa,
                                    "motivo": f"supera {MAX_BYTES} bytes ({tamano})"
                                })
                                continue

                            # Crear o actualizar
                            if ruta_relativa in data["tree"]:
                                data["tree"][ruta_relativa]["content"] = contenido
                                data["tree"][ruta_relativa]["modified"] = self._now()
                                resultado["actualizadas"] += 1
                            else:
                                self._crear_directorios_intermedios(data, ruta_relativa)
                                data["tree"][ruta_relativa] = {
                                    "type": "note",
                                    "content": contenido,
                                    "modified": self._now(),
                                    "children": set(),
                                }
                                # Actualizar children del padre
                                padre = self._ruta_padre(ruta_relativa)
                                if padre:
                                    data["tree"][padre]["children"].add(ruta_relativa)
                                else:
                                    data["children"].add(ruta_relativa)
                                resultado["creadas"] += 1

                        except Exception as exc:
                            resultado["omitidas"] += 1
                            resultado["errores"].append({
                                "path": ruta_relativa,
                                "motivo": str(exc)
                            })

            except zipfile.BadZipFile:
                resultado["errores"].append({
                    "path": "zip",
                    "motivo": "archivo ZIP corrupto o inválido"
                })

            return resultado

