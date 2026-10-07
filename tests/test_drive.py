"""Backend de Google Drive: contrato compartido y reglas propias de Drive.

Ningún test toca la red: `DriveFalso` implementa los cuatro endpoints de
Drive v3 que usa `ClienteDrive` y se engancha con `httpx.MockTransport`.

Dos bloques:

- `ContratoTresBackendsTests` corre el mismo guion en `memory`,
  `filesystem` y `drive` y exige el mismo resultado: un backend nuevo no
  puede cambiar el comportamiento que el resto de la app ya espera.
- `DriveTests` cubre lo que solo existe en Drive: la raíz en
  `appDataFolder`, nombres no únicos, la marca de modificación en la
  `description`, la paginación, los reintentos por cuota y la traducción
  de 401/404.

`TestApiDriveTests` baja eso a la API: qué código de estado responde
FastAPI cuando Drive falla.
"""

import json
import os
import tempfile
import unittest
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
from test_auth import AuthTestCase, sin_google

import purplemd
from purplemd_storage import (
    ClienteDrive,
    DirectorioNoEncontrado,
    DriveStorage,
    ErrorDrive,
    FilesystemStorage,
    MemoryStorage,
    NoEncontradoEnDrive,
    Storage,
    TokenVencido,
)
from purplemd_storage.drive import ESPACIO, MIME_CARPETA, TOPE_REINTENTOS

# Path de `files.list` (sin el host: `Request.url.path` no lo trae).
RUTA_LISTA = "/drive/v3/files"

def dormir_silencioso(_segundos: float) -> None:
    """`time.sleep` de mentira: los tests no esperan los reintentos."""


def _error_drive(codigo: int, mensaje: str, motivo: str = "") -> httpx.Response:
    cuerpo: dict = {"code": codigo, "message": mensaje}
    if motivo:
        cuerpo["errors"] = [{"reason": motivo, "message": mensaje}]
    return httpx.Response(codigo, json={"error": cuerpo})


class DriveFalso:
    """Drive v3 mínimo: los endpoints que toca `ClienteDrive`.

    - `fallos`: cola de `(método, subcadena del path, respuesta)` que se
      descuenta antes de responder de verdad, para simular cuota agotada,
      401 o un 500 puntual.
    - `tamano_pagina`: fuerza `nextPageToken` para probar la paginación.
    """

    def __init__(self, *, tamano_pagina: int | None = None):
        self.archivos: dict[str, dict] = {}
        self.contenidos: dict[str, bytes] = {}
        self.pedidos: list[httpx.Request] = []
        self.fallos: list[tuple[str, str, httpx.Response]] = []
        self.tamano_pagina = tamano_pagina
        self._contador = 0
        # Reloj estrictamente creciente: si dos archivos cayeran en el
        # mismo microsegundo la lista de proyectos sería ambigua.
        self._reloj = 1_700_000_000.0

    # --- construcción del estado ---

    def crear(
        self, nombre: str, padre: str, *, carpeta: bool = False, contenido: str = ""
    ) -> str:
        """Agrega un archivo sin pasar por la API (para sembrar tests)."""
        self._contador += 1
        identificador = f"id-{self._contador}"
        ahora = self._ahora()
        self.archivos[identificador] = {
            "id": identificador,
            "name": nombre,
            "mimeType": MIME_CARPETA if carpeta else "text/plain",
            "parents": [padre],
            "modifiedTime": ahora,
            # Lo pide `buscar_raiz` para fijar el orden de las raíces.
            "createdTime": ahora,
            "description": "",
        }
        self.contenidos[identificador] = contenido.encode("utf-8")
        return identificador

    def carpeta(self, nombre: str, padre: str) -> str:
        return self.crear(nombre, padre, carpeta=True)

    def hijos_de(self, identificador: str) -> list[dict]:
        return [i for i in self.archivos.values() if identificador in i["parents"]]

    def por_nombre(self, nombre: str) -> list[dict]:
        return [i for i in self.archivos.values() if i["name"] == nombre]

    # --- HTTP ---

    def _ahora(self) -> str:
        self._reloj = max(self._reloj + 1e-6, __import__("time").time())
        return (
            datetime.fromtimestamp(self._reloj, UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )

    @staticmethod
    def _meta(item: dict) -> dict:
        return {
            clave: item[clave]
            for clave in (
                "id",
                "name",
                "mimeType",
                "parents",
                "modifiedTime",
                "createdTime",
                "description",
            )
        }

    def _consumir_fallo(self, request: httpx.Request) -> httpx.Response | None:
        for indice, (metodo, subcadena, respuesta) in enumerate(self.fallos):
            if request.method == metodo and subcadena in request.url.path:
                self.fallos.pop(indice)
                return respuesta
        return None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.pedidos.append(request)
        forzado = self._consumir_fallo(request)
        if forzado is not None:
            return forzado

        metodo = request.method
        ruta = request.url.path
        params = request.url.params

        if ruta.startswith("/upload/drive/v3/files/"):
            return self._subir(request, ruta.rsplit("/", 1)[-1], params)

        if ruta == "/drive/v3/files":
            if metodo == "GET":
                return self._listar(params)
            if metodo == "POST":
                cuerpo = json.loads(request.content)
                identificador = self.crear(
                    cuerpo["name"],
                    cuerpo["parents"][0],
                    carpeta=cuerpo.get("mimeType") == MIME_CARPETA,
                )
                self.archivos[identificador]["description"] = cuerpo.get(
                    "description", ""
                )
                if cuerpo.get("mimeType") != MIME_CARPETA:
                    # `crear_archivo` sube el contenido en el segundo paso.
                    self.contenidos[identificador] = b""
                return httpx.Response(200, json=self._meta(self.archivos[identificador]))

        if ruta.startswith("/drive/v3/files/"):
            return self._metadatos(request, ruta.rsplit("/", 1)[-1], params, metodo)

        return _error_drive(400, f"{metodo} {ruta} no soportado por el Drive falso")

    def _listar(self, params: httpx.QueryParams) -> httpx.Response:
        consulta = params.get("q", "")
        if consulta.startswith("name = "):
            partes = consulta.split("'")
            nombre, mime, espacio = partes[1], partes[3], partes[5]
            encontrados = [
                item
                for item in self.archivos.values()
                if item["name"] == nombre
                and item["mimeType"] == mime
                and espacio in item["parents"]
            ]
            return httpx.Response(200, json={"files": [self._meta(i) for i in encontrados]})

        padre = consulta.split("'")[1]
        hijos = self.hijos_de(padre)
        if self.tamano_pagina is None:
            return httpx.Response(200, json={"files": [self._meta(i) for i in hijos]})

        desde = int(params.get("pageToken") or 0)
        hasta = desde + self.tamano_pagina
        cuerpo: dict = {"files": [self._meta(i) for i in hijos[desde:hasta]]}
        if hasta < len(hijos):
            cuerpo["nextPageToken"] = str(hasta)
        return httpx.Response(200, json=cuerpo)

    def _metadatos(
        self, request: httpx.Request, identificador: str, params, metodo: str
    ) -> httpx.Response:
        if identificador not in self.archivos:
            return _error_drive(404, f"File not found: {identificador}")
        item = self.archivos[identificador]

        if metodo == "GET":
            if params.get("alt") == "media":
                return httpx.Response(200, content=self.contenidos.get(identificador, b""))
            return httpx.Response(200, json=self._meta(item))

        if metodo == "PATCH":
            cuerpo = json.loads(request.content) if request.content else {}
            item.update({k: v for k, v in cuerpo.items() if k in ("name", "description")})
            if "addParents" in params:
                item["parents"] = [params["addParents"]]
            item["modifiedTime"] = self._ahora()
            return httpx.Response(200, json=self._meta(item))

        if metodo == "DELETE":
            # Drive responde 204 y el archivo queda fuera de la papelera
            # cuando se pide `?trashed=false`, que `ClienteDrive` no manda.
            del self.archivos[identificador]
            self.contenidos.pop(identificador, None)
            return httpx.Response(204)

        return _error_drive(400, f"{metodo} no soportado")

    def _subir(self, request: httpx.Request, identificador: str, params) -> httpx.Response:
        if identificador not in self.archivos:
            return _error_drive(404, f"File not found: {identificador}")
        if request.method != "PATCH" or params.get("uploadType") != "media":
            return _error_drive(400, "subida no soportada")
        self.contenidos[identificador] = request.content
        self.archivos[identificador]["modifiedTime"] = self._ahora()
        return httpx.Response(200, json=self._meta(self.archivos[identificador]))

    def pedidos_a(self, sufijo: str) -> list[httpx.Request]:
        return [p for p in self.pedidos if p.url.path.endswith(sufijo)]


def drive_storage(
    drive: DriveFalso, *, dormir: Callable[[float], None] = dormir_silencioso
) -> DriveStorage:
    """`DriveStorage` colgado del Drive falso, sin dormir ni salir a la red."""
    cliente = ClienteDrive(
        lambda: "token-de-prueba",
        http=httpx.Client(transport=httpx.MockTransport(drive.handler)),
        dormir=dormir,
    )
    return DriveStorage(cliente)


# --------------------------------------------------------------------------
# Contrato
# --------------------------------------------------------------------------


def _guion(storage) -> list[str]:
    """Corre el mismo guion en cualquier backend y anota lo que pasó.

    Solo se registran cosas comparables entre backends: nombres, rutas,
    contenidos y **el tipo** de la excepción (los mensajes son texto
    libre de cada implementación y compararlos sería acoplar el test a la
    redacción de cada archivo).
    """
    registro: list[str] = []

    def paso(accion, funcion, *args, formatear=None, **kwargs):
        try:
            resultado = funcion(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - el tipo es el contrato
            registro.append(f"{accion} → {type(exc).__name__}")
            return None
        texto = formatear(resultado) if formatear else "ok"
        registro.append(f"{accion} → {texto}")
        return resultado

    nombres = lambda lista: "[" + ", ".join(p.name for p in lista) + "]"  # noqa: E731
    arbol = lambda a: "[" + ", ".join(f"{e.type}:{e.path}" for e in a.entries) + "]"  # noqa: E731
    nota = lambda n: f"{n.path}={n.content!r}"  # noqa: E731
    dirs = lambda d: f"{d.path}"  # noqa: E731

    paso("listar vacío", storage.listar_proyectos, formatear=nombres)
    paso("crear p1", storage.crear_proyecto, "p1")
    paso("crear p1 otra vez", storage.crear_proyecto, "p1")
    paso("crear p2", storage.crear_proyecto, "p2")
    paso("crear nombre malo", storage.crear_proyecto, "../colada")
    paso("listar", storage.listar_proyectos, formatear=nombres)
    paso("renombrar p1", storage.renombrar_proyecto, "p1", "uno")
    paso("renombrar p1 igual", storage.renombrar_proyecto, "uno", "uno")
    paso("renombrar a ocupado", storage.renombrar_proyecto, "uno", "p2")
    paso("renombrar inexistente", storage.renombrar_proyecto, "fantasma", "x")

    paso("crear nota raíz", storage.crear_nota, "uno", "portada", "# hola", formatear=nota)
    paso("crear nota raíz otra vez", storage.crear_nota, "uno", "portada", "# x")
    paso("crear nota en carpeta", storage.crear_nota, "uno", "carp/una", "cuerpo", formatear=nota)
    paso("crear nota profunda", storage.crear_nota, "uno", "a/b/c", "x", formatear=nota)
    paso("crear nota en proyecto fantasma", storage.crear_nota, "fantasma", "n", "x")
    paso("crear ruta malformada", storage.crear_nota, "uno", "carp//una", "x")

    paso("leer nota", storage.leer_nota, "uno", "portada", formatear=nota)
    paso("leer nota ausente", storage.leer_nota, "uno", "no-existe")
    paso("leer de proyecto ausente", storage.leer_nota, "fantasma", "portada")
    paso("guardar nota", storage.guardar_nota, "uno", "portada", "# editada", formatear=nota)
    paso("guardar nota ausente", storage.guardar_nota, "uno", "fantasma", "x")

    paso("árbol", storage.arbol_proyecto, "uno", formatear=arbol)
    paso("árbol de proyecto ausente", storage.arbol_proyecto, "fantasma")

    paso("renombrar nota", storage.renombrar_nota, "uno", "portada", "portada2", formatear=nota)
    paso("renombrar a ocupada", storage.renombrar_nota, "uno", "carp/una", "c")
    paso("renombrar nota ausente", storage.renombrar_nota, "uno", "nope", "si")
    paso(
        "mover nota a otra carpeta",
        storage.mover_nota,
        "uno",
        "portada2",
        "carpeta2/portada2",
        formatear=nota,
    )
    paso("mover nota a ocupada", storage.mover_nota, "uno", "carp/una", "carp/otra")
    paso("mover nota a sí misma", storage.mover_nota, "uno", "a/b/c", "a/b/c", formatear=nota)

    paso(
        "renombrar directorio",
        storage.renombrar_directorio,
        "uno",
        "a",
        "alfabeto",
        formatear=dirs,
    )
    paso("renombrar directorio ausente", storage.renombrar_directorio, "uno", "nope", "si")
    paso("mover directorio dentro de sí", storage.mover_directorio, "uno", "carp", "carp/dentro")
    paso(
        "mover directorio al lado",
        storage.mover_directorio,
        "uno",
        "alfabeto",
        "junto",
        formatear=dirs,
    )
    paso("borrar directorio lleno", storage.eliminar_directorio, "uno", "junto")
    paso(
        "borrar directorio lleno con recursive",
        storage.eliminar_directorio,
        "uno",
        "junto",
        recursive=True,
    )
    paso("borrar directorio ausente", storage.eliminar_directorio, "uno", "nope")

    paso(
        "nota demasiado grande",
        storage.crear_nota,
        "uno",
        "grande",
        "x" * (purplemd.MAX_BYTES + 1),
    )

    paso("borrar nota", storage.eliminar_nota, "uno", "carp/otra")
    paso("borrar nota otra vez", storage.eliminar_nota, "uno", "carp/otra")

    paso("exportar", storage.exportar_proyecto, "uno")
    paso("exportar ausente", storage.exportar_proyecto, "fantasma")

    paso("eliminar proyecto", storage.eliminar_proyecto, "uno")
    paso("eliminar proyecto otra vez", storage.eliminar_proyecto, "uno")
    paso("listar final", storage.listar_proyectos, formatear=nombres)
    paso("árbol de eliminado", storage.arbol_proyecto, "uno")
    paso("operativo", storage.esta_operativo, formatear=lambda ok: str(bool(ok)))
    return registro


class ContratoTresBackendsTests(unittest.TestCase):
    """Las tres implementaciones de `Storage` responden igual."""

    # Un guion es una lista larga: sin esto, el fallo se reporta como
    # «Diff is 2079 characters long» y no sirve para diagnosticar.
    maxDiff = None

    def _backends(self) -> dict[str, Storage]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return {
            "memory": MemoryStorage(),
            "filesystem": FilesystemStorage(Path(tmp.name)),
            "drive": drive_storage(DriveFalso()),
        }

    def test_el_mismo_guion_da_el_mismo_resultado(self):
        guiones = {}
        for nombre, storage in self._backends().items():
            guiones[nombre] = _guion(storage)
        self.assertEqual(guiones["memory"], guiones["filesystem"])
        self.assertEqual(guiones["memory"], guiones["drive"])

    def test_import_export_round_trip_en_los_tres(self):
        for nombre, storage in self._backends().items():
            with self.subTest(backend=nombre):
                storage.crear_proyecto("origen")
                storage.crear_nota("origen", "portada", "# hola")
                storage.crear_nota("origen", "sub/nota", "x")
                copia = storage.importar_proyecto(
                    "copia", storage.exportar_proyecto("origen")
                )
                self.assertEqual(copia["creadas"], 2, copia)
                self.assertEqual(storage.leer_nota("copia", "portada").content, "# hola")
                self.assertEqual(storage.leer_nota("copia", "sub/nota").content, "x")

    def test_los_tres_cumplen_el_protocolo(self):
        from purplemd_storage.protocol import Storage

        for nombre, storage in self._backends().items():
            with self.subTest(backend=nombre):
                self.assertIsInstance(storage, Storage)

    def test_eliminar_un_proyecto_inexistente_es_un_error_de_no_encontrado(self):
        """Todos responden igual antes de que la API lo traduzca a 404."""
        for nombre, storage in self._backends().items():
            with self.subTest(backend=nombre):
                with self.assertRaises((purplemd.ProyectoNoExiste, DirectorioNoEncontrado)):
                    storage.eliminar_proyecto("no-existe")


# --------------------------------------------------------------------------
# Reglas propias de Drive
# --------------------------------------------------------------------------


class DriveTests(unittest.TestCase):
    """Lo que Drive hace distinto del filesystem."""

    def setUp(self):
        self.drive = DriveFalso()
        self.storage = drive_storage(self.drive)

    # --- Raíz y appDataFolder ---

    def test_sin_nada_la_lista_de_proyectos_esta_vacia(self):
        self.assertEqual(self.storage.listar_proyectos(), [])

    def test_la_raiz_se_crea_en_appdata_folder(self):
        """`parents: ["appDataFolder"]` es la única forma de apuntar ahí."""
        self.storage.crear_proyecto("p")
        creados = [
            json.loads(p.content)
            for p in self.drive.pedidos
            if p.method == "POST" and p.url.path == RUTA_LISTA
        ]
        self.assertTrue(creados)
        self.assertEqual(creados[0]["parents"], [ESPACIO])
        self.assertEqual(creados[0]["mimeType"], MIME_CARPETA)

    def test_una_carpeta_projects_de_proyecto_no_confunde_a_la_raiz(self):
        """La raíz vive una capa más abajo: la query la acota a appDataFolder."""
        raiz = self.drive.carpeta("projects", ESPACIO)
        self.drive.carpeta("projects", raiz)
        self.assertEqual(self.storage._cliente.buscar_raiz(), raiz)

    def test_con_dos_raices_elige_siempre_la_misma(self):
        """Drive no promete el orden de los resultados: hay que fijarlo.

        Dos raíces solo puede salir de una carrera entre dos `crear_raiz()`
        (dos peticiones en paralelo sobre un Drive vacío). Si la elección
        dependiera del orden que devuelva Drive, los proyectos quedarían
        repartidos entre dos árboles y aparecerían y desaparecerían entre
        una petición y la siguiente.
        """
        vieja = self.drive.carpeta("projects", ESPACIO)
        nueva = self.drive.carpeta("projects", ESPACIO)
        self.drive.archivos[vieja]["createdTime"] = "2020-01-01T00:00:00Z"
        self.drive.archivos[nueva]["createdTime"] = "2024-06-01T00:00:00Z"

        cliente = self.storage._cliente
        self.assertEqual(cliente.buscar_raiz(), vieja)
        # Drive la devuelve del revés en la siguiente llamada.
        self.drive.archivos = dict(reversed(list(self.drive.archivos.items())))
        self.assertEqual(cliente.buscar_raiz(), vieja)

    def test_con_raices_nacidas_juntas_desempata_el_id(self):
        """`createdTime` puede empatar al segundo: el `id`, en cambio, es único."""
        primera = self.drive.carpeta("projects", ESPACIO)
        segunda = self.drive.carpeta("projects", ESPACIO)
        mismo = "2024-06-01T00:00:00Z"
        self.drive.archivos[primera]["createdTime"] = mismo
        self.drive.archivos[segunda]["createdTime"] = mismo
        esperado = min(primera, segunda)

        cliente = self.storage._cliente
        for _ in range(3):
            self.drive.archivos = dict(reversed(list(self.drive.archivos.items())))
            self.assertEqual(cliente.buscar_raiz(), esperado)

    def test_el_espacio_es_appdata_folder_en_el_listado(self):
        """Sin `spaces`, `files.list` solo mira `drive` y devuelve vacío."""
        self.storage.crear_proyecto("p")
        self.storage.crear_nota("p", "una", "hola")
        listados = [
            p
            for p in self.drive.pedidos
            if p.method == "GET" and p.url.path == RUTA_LISTA
        ]
        self.assertTrue(listados)
        sin_espacio = [p for p in listados if p.url.params.get("spaces") != ESPACIO]
        self.assertEqual(sin_espacio, [], [str(p.url) for p in sin_espacio])

    # --- Nombres no únicos ---

    def test_dos_archivos_iguales_usa_el_primero_y_avisa(self):
        self.storage.crear_proyecto("p")
        carpeta = self._un_proyecto()["id"]
        self.drive.crear("dup.md", carpeta, contenido="primero")
        self.drive.crear("dup.md", carpeta, contenido="segundo")

        with self.assertLogs("purplemd", level="WARNING") as bitacora:
            nota = self.storage.leer_nota("p", "dup")
        self.assertEqual(nota.content, "primero")
        self.assertTrue(any("Drive devuelve" in linea for linea in bitacora.output))

    def test_dos_carpetas_iguales_usa_la_primera(self):
        self.storage.crear_proyecto("p")
        carpeta = self._un_proyecto()["id"]
        self.drive.carpeta("doble", carpeta)
        self.drive.carpeta("doble", carpeta)
        with self.assertLogs("purplemd", level="WARNING"):
            self.storage.crear_nota("p", "doble/n", "contenido")
        # Si eligiera mal, crearía una tercera carpeta «doble».
        self.assertEqual(len(self.drive.por_nombre("doble")), 2)

    # --- La marca de modificación ---

    def test_la_marca_de_modificacion_vive_en_el_proyecto(self):
        """Es el motivo entero de no usar `modifiedTime` de Drive.

        Drive no mueve el `modifiedTime` de una carpeta cuando cambian sus
        hijos, así que el epoch va en la `description` del proyecto. Si se
        escribiera en la nota (que era lo que pasaba), la lista de
        proyectos se quedaría con la fecha vieja para siempre.
        """
        self.storage.crear_proyecto("p")
        self.storage.crear_nota("p", "una", "hola")

        proyecto = self._un_proyecto()
        nota = self._un_archivo("una.md")
        self.assertTrue(proyecto["description"].isdigit(), proyecto)
        self.assertEqual(nota["description"], "", nota)

    def test_guardar_tambien_mueve_la_marca_del_proyecto(self):
        self.storage.crear_proyecto("p")
        self.storage.crear_nota("p", "una", "hola")
        self.storage.guardar_nota("p", "una", "editada")
        self.assertTrue(self._un_proyecto()["description"].isdigit())

    def test_eliminar_tambien_mueve_la_marca_del_proyecto(self):
        self.storage.crear_proyecto("p")
        self.storage.crear_nota("p", "una", "hola")
        self.storage.eliminar_nota("p", "una")
        self.assertTrue(self._un_proyecto()["description"].isdigit())

    def _primero_de(self, nombre: str) -> str:
        return next(i["id"] for i in self.drive.por_nombre(nombre))

    def _un_proyecto(self) -> dict:
        """La única carpeta de proyecto que hay (hay una sola raíz)."""
        raiz = self._primero_de("projects")
        return self.drive.hijos_de(raiz)[0]

    def _un_archivo(self, nombre: str) -> dict:
        return self.drive.por_nombre(nombre)[0]

    def test_los_proyectos_se_listan_por_orden_de_modificacion(self):
        import time

        self.storage.crear_proyecto("primero")
        time.sleep(0.02)
        self.storage.crear_proyecto("segundo")
        nombres = [p.name for p in self.storage.listar_proyectos()]
        self.assertEqual(nombres, ["segundo", "primero"])

    def test_los_archivos_invalidos_no_aparecen_en_el_arbol(self):
        self.storage.crear_proyecto("p")
        raiz = self._primero_de("projects")
        carpeta = self.drive.hijos_de(raiz)[0]["id"]
        self.drive.crear("no-markdown.txt", carpeta, contenido="x")
        self.drive.crear(".oculto.md", carpeta, contenido="x")
        caminos = [e.path for e in self.storage.arbol_proyecto("p").entries]
        self.assertEqual(caminos, [])

    # --- Paginación y caché ---

    def test_das_paginas_se_concatenan(self):
        drive = DriveFalso(tamano_pagina=2)
        storage = drive_storage(drive)
        storage.crear_proyecto("p")
        for n in range(5):
            storage.crear_nota("p", f"nota{n}", "x")
        # La carpeta del proyecto y sus 5 notas: más de dos páginas.
        paginas = [p for p in drive.pedidos if "pageToken" in p.url.params]
        self.assertTrue(paginas)
        caminos = [e.path for e in storage.arbol_proyecto("p").entries]
        self.assertEqual(caminos, ["nota0", "nota1", "nota2", "nota3", "nota4"])

    def test_el_listado_se_cachea_dentro_del_request(self):
        self.storage.crear_proyecto("p")
        cliente = self.storage._cliente
        raiz = cliente.buscar_raiz()
        assert raiz is not None
        antes = len([p for p in self.drive.pedidos if p.method == "GET"])
        cliente.listar(raiz)
        cliente.listar(raiz)
        cliente.listar(raiz)
        despues = len([p for p in self.drive.pedidos if p.method == "GET"])
        self.assertEqual(antes + 1, despues)

    # --- Borrado y deshacer ---

    def test_el_borrado_es_permanente_y_no_a_papelera(self):
        """Dejarlo en la papelera consumiría cuota y no es «sin vuelta atrás»."""
        self.storage.crear_proyecto("p")
        self.storage.crear_nota("p", "una", "hola")
        archivo = self._un_archivo("una.md")
        borrar = [
            p
            for p in self.drive.pedidos
            if p.method == "DELETE" and p.url.path.endswith(archivo["id"])
        ]
        self.assertEqual(len(borrar), 0)  # aún no se borró nada
        self.storage.eliminar_nota("p", "una")
        borrar = [
            p
            for p in self.drive.pedidos
            if p.method == "DELETE" and p.url.path.endswith(archivo["id"])
        ]
        self.assertEqual(len(borrar), 1)
        self.assertNotIn("trashed", borrar[0].url.params)
        self.assertNotIn(archivo["id"], self.drive.archivos)

    def test_si_la_subida_falla_se_deshace_el_archivo(self):
        """`crear_archivo` es de dos pasos: si el segundo cae, el primero no deja basura."""
        self.storage.crear_proyecto("p")
        self.drive.fallos.append(("PATCH", "/upload/drive/v3/", _error_drive(500, "quebrado")))
        with self.assertRaises(ErrorDrive):
            self.storage.crear_nota("p", "una", "hola")
        self.assertEqual(self.drive.por_nombre("una.md"), [])

    # --- Estado operativo ---

    def test_esta_operativo_no_hace_llamadas_a_la_red(self):
        """`/health` se consulta cada pocos segundos y cada chequeo cuesta cuota."""
        self.storage.crear_proyecto("p")
        del self.drive.pedidos[:]
        self.assertTrue(self.storage.esta_operativo())
        self.assertEqual(self.drive.pedidos, [])

    def test_esta_operativo_es_false_si_el_token_no_se_puede_refrescar(self):
        cliente = ClienteDrive(
            lambda: (_ for _ in ()).throw(RuntimeError("no hay refresh")),
            http=httpx.Client(transport=httpx.MockTransport(self.drive.handler)),
            dormir=dormir_silencioso,
        )
        self.assertFalse(DriveStorage(cliente).esta_operativo())


# --------------------------------------------------------------------------
# Cuota, token y errores
# --------------------------------------------------------------------------


class ReintentosTests(unittest.TestCase):
    def setUp(self):
        self.drive = DriveFalso()
        self.esperas: list[float] = []
        self.storage = drive_storage(self.drive, dormir=self.esperas.append)

    def _limitacion(self) -> httpx.Response:
        return _error_drive(403, "User rate limit exceeded", "userRateLimitExceeded")

    def test_reintenta_con_backoff_y_pasa(self):
        self.drive.fallos.extend(
            ("GET", "/drive/v3/files", self._limitacion()) for _ in range(3)
        )
        self.assertEqual(self.storage.listar_proyectos(), [])
        self.assertEqual(len(self.esperas), 3)
        # Backoff exponencial: 1 s, 2 s y 4 s (más jitter de hasta 0.5 s).
        self.assertGreater(self.esperas[1], self.esperas[0])
        self.assertGreater(self.esperas[2], self.esperas[1])

    def test_tras_el_tope_de_reintentos_se_ritira(self):
        self.drive.fallos.extend(
            ("GET", "/drive/v3/files", _error_drive(429, "rate limit")) for _ in range(99)
        )
        with self.assertRaises(ErrorDrive) as ctx:
            self.storage.listar_proyectos()
        self.assertIn(str(TOPE_REINTENTOS), str(ctx.exception))
        self.assertEqual(len(self.esperas), TOPE_REINTENTOS)

    def test_un_401_no_se_reintenta_y_es_un_token_vencido(self):
        self.drive.fallos.append(("GET", "/drive/v3/files", _error_drive(401, "invalidado")))
        with self.assertRaises(TokenVencido):
            self.storage.listar_proyectos()
        self.assertEqual(self.esperas, [])

    def test_un_404_es_no_encontrado_y_tampoco_reintenta(self):
        cliente = self.storage._cliente
        self.drive.fallos.append(("GET", "/drive/v3/files/", _error_drive(404, "ausente")))
        with self.assertRaises(NoEncontradoEnDrive):
            cliente.meta("id-404")
        self.assertEqual(self.esperas, [])

    def test_un_error_de_drive_lleva_el_detalle_sin_volcar_el_cuerpo(self):
        self.drive.fallos.append(("GET", "/drive/v3/files", _error_drive(403, "sin permiso")))
        with self.assertRaises(ErrorDrive) as ctx:
            self.storage.listar_proyectos()
        self.assertIn("403", str(ctx.exception))
        self.assertIn("sin permiso", str(ctx.exception))

    def test_el_token_viaja_en_authorization_bearer(self):
        self.storage.listar_proyectos()
        autenticaciones = [
            p.headers.get("Authorization") for p in self.drive.pedidos
        ]
        self.assertTrue(autenticaciones)
        self.assertTrue(all(a == "Bearer token-de-prueba" for a in autenticaciones))

    def test_un_error_de_red_no_es_un_500(self):
        roto = ClienteDrive(
            lambda: "t",
            http=httpx.Client(
                transport=httpx.MockTransport(
                    lambda _r: (_ for _ in ()).throw(httpx.ConnectError("sin red"))
                )
            ),
            dormir=dormir_silencioso,
        )
        with self.assertRaises(ErrorDrive) as ctx:
            roto.listar("x")
        self.assertIn("sin red", str(ctx.exception))


# --------------------------------------------------------------------------
# Bajada a la API
# --------------------------------------------------------------------------


class ApiDriveTests(AuthTestCase):
    """Qué responde FastAPI cuando Drive falla con la sesión puesta."""

    def setUp(self):
        super().setUp()
        self.drive = DriveFalso()
        self.login()
        self._drive_env = patch.dict(os.environ, {"PURPLEMD_STORAGE": "drive"})
        self._drive_env.start()
        self.addCleanup(self._drive_env.stop)
        patcher = patch(
            "purplemd_storage.drive.cliente_por_defecto",
            return_value=httpx.Client(
                transport=httpx.MockTransport(self.drive.handler)
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_con_drive_la_api_funciona(self):
        r = self.client.post("/api/projects", json={"name": "cuaderno"})
        self.assertEqual(r.status_code, 201, r.text)
        r = self.client.post(
            "/api/projects/cuaderno/notes",
            json={"path": "entrada", "content": "# hola"},
        )
        self.assertEqual(r.status_code, 201, r.text)
        r = self.client.get("/api/projects/cuaderno/notes/entrada")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["content"], "# hola")

    def test_un_401_de_drive_se_traduce_en_volver_a_conectar(self):
        self.drive.fallos.append(
            ("GET", "/drive/v3/files", _error_drive(401, "invalidado"))
        )
        r = self.client.get("/api/projects")
        self.assertEqual(r.status_code, 401)
        self.assertIn("Google", r.json()["detail"])

    def test_un_error_de_drive_se_traduce_en_503(self):
        self.drive.fallos.append(("GET", "/drive/v3/files", _error_drive(500, "caído")))
        r = self.client.get("/api/projects")
        self.assertEqual(r.status_code, 503)

    def test_sin_integracion_drive_no_se_puede_elegir(self):
        """`get_storage()` no sabe de qué cuenta hablar: el error es intencional."""
        with sin_google(), patch.dict(os.environ, {"PURPLEMD_STORAGE": "drive"}):
            r = self.client.get("/api/projects")
        self.assertEqual(r.status_code, 503)
        self.assertIn("Google", r.json()["detail"])

    def test_los_proyectos_de_drive_se_listan_por_la_api(self):
        self.client.post("/api/projects", json={"name": "a"})
        self.client.post("/api/projects", json={"name": "b"})
        nombres = [p["name"] for p in self.client.get("/api/projects").json()["projects"]]
        self.assertEqual(nombres, ["b", "a"])


if __name__ == "__main__":
    unittest.main()
