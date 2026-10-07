"""Backend de almacenamiento sobre Google Drive.

Tercera implementación del protocolo `Storage`: las notas de un usuario
viven en **su** Google Drive, en la carpeta oculta `appDataFolder`,
bajo la misma estructura que usa el backend local:

```
appDataFolder/projects/{proyecto}/{subcarpeta}/{nota}.md
```

`appDataFolder` es invisible en la interfaz de Drive y solo la puede ver
esta app, así que el usuario no puede romper la estructura desde el
explorador de archivos. El alcance OAuth es `drive.file`: Google pide
consentimiento solo «para los archivos que creó esta app».

Tres detalles que definen el diseño:

- **Los nombres no son únicos en Drive.** Dos archivos pueden llamarse
  igual en la misma carpeta, algo impensable en un filesystem. Toda
  operación busca por `padre + nombre` y crea solo si no hay coincidencia;
  si aparece más de una se registra en `WARNING` y se usa la primera.
- **Drive no tiene `mtime` en las carpetas.** Modificar una nota no
  mueve el `modifiedTime` de la carpeta que la contiene, con lo que la
  lista de proyectos (ordenada por modificación) quedaría siempre vieja.
  Por eso cada escritura guarda el epoch en la `description` del
  proyecto, que sí se actualiza.
- **La cuota es finita y pesa por operación** (`files.list` = 100
  unidades, `files.update` = 50). Google devuelve `403 User rate limit
  exceeded` o `429` y pide *backoff exponencial*, que es lo que hace
  `_solicitar` antes de rendirse.

El cliente HTTP se inyecta, así que los tests corren contra un
`httpx.MockTransport` con un Drive falso: ningún test toca la red.
"""

import json
import logging
import random
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from purplemd_storage.protocol import (
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
from purplemd_storage.zipio import leer_notas_zip

logger = logging.getLogger("purplemd")

API = "https://www.googleapis.com/drive/v3"
API_SUBIDA = "https://www.googleapis.com/upload/drive/v3"

MIME_CARPETA = "application/vnd.google-apps.folder"
MIME_TEXTO = "text/plain; charset=utf-8"

# Carpeta oculta de la app y la que agrupa los proyectos dentro de ella.
ESPACIO = "appDataFolder"
RAIZ = "projects"

CAMPOS_LISTA = "nextPageToken,files(id,name,mimeType,parents,modifiedTime,description)"
CAMPOS_META = "id,name,mimeType,parents,modifiedTime,description"

# Drive pagina con `pageSize` pero además cobra por campo pedido: un
# `fields` corto devuelve páginas más llenas y gasta menos cuota.
TOPE_PAGINA = 1000
# Reintentos sobre 403/429. Google recomienda backoff exponencial con
# tope y jitter; cuatro intentos llegan hasta ~8 s sin clavar el request.
TOPE_REINTENTOS = 4
# Validez de un listado cacheado dentro del mismo request.
TTL_LISTADO_SEG = 15.0

# El contenido de una nota es texto UTF-8; esto solo documenta la
# extensión que se le pone en Drive (el nombre ya lleva `.md`).
_EXT_MIME = "text/plain"


class ErrorDrive(Exception):  # noqa: N818
    """Fallo de Google Drive que no depende de la sesión del usuario."""


class TokenVencido(ErrorDrive):  # noqa: N818
    """El access token dejó de servir y no se pudo refrescar."""


class NoEncontradoEnDrive(ErrorDrive):  # noqa: N818
    """Drive respondió 404 para un archivo que la app esperaba."""


_CLIENTE: httpx.Client | None = None
_CANDADO = threading.Lock()


def cliente_por_defecto() -> httpx.Client:
    """Cliente HTTP compartido: reusa conexiones entre requests.

    Se inyecta en los tests con `httpx.MockTransport` para simular Drive.
    """
    global _CLIENTE
    with _CANDADO:
        if _CLIENTE is None:
            _CLIENTE = httpx.Client(timeout=httpx.Timeout(30.0))
        return _CLIENTE


def _epoch_de_iso(iso: str | None) -> float:
    """Convierte `modifiedTime` de Drive a epoch, o 0 si no se puede."""
    if not iso:
        return 0.0
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        logger.warning("modifiedTime ilegible de Drive: %r", iso)
        return 0.0


def _modificado(item: dict) -> float:
    """Modificación de un elemento del árbol.

    Prefiere la `description` (donde PurpleMD guarda el epoch real del
    proyecto) y cae a `modifiedTime`, que Drive sí actualiza al tocar el
    archivo.
    """
    descripcion = item.get("description")
    if descripcion:
        try:
            return float(descripcion)
        except (TypeError, ValueError):
            pass
    return _epoch_de_iso(item.get("modifiedTime"))


def _nombre_valido(nombre: str) -> bool:
    """¿El nombre de Drive pasa la validación de PurpleMD? Para filtrar."""
    try:
        validar_nombre(nombre)
    except NombreInvalido:
        return False
    return True


def _ruta_del_proyecto(ruta: str) -> str:
    """Carpeta que contiene una ruta lógica (`a/b/nota` → `a/b`)."""
    return ruta.rpartition("/")[0]


def _segmento(ruta: str) -> str:
    """Último segmento de una ruta lógica (`a/b/nota` → `nota`)."""
    return ruta.rpartition("/")[2]


class ClienteDrive:
    """Capa HTTP contra la API de Drive: listados, escrituras y reintentos.

    Es un objeto por storage (y el storage es por request), así que sus
    cachés solo viven dentro de una petición: evitan repetir el mismo
    `files.list` al caminar un árbol, no aceleran entre requests. El
    estado compartido entre requests es únicamente el `httpx.Client`.
    """

    def __init__(
        self,
        token: Callable[[], str],
        *,
        http: httpx.Client | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        """Args:
            token: Devuelve un access token vigente (refresca si hace falta).
            http: Cliente HTTP inyectable para los tests.
            dormir: `time.sleep` reemplazable para no dormir en tests.
        """
        self._token = token
        self._http = http or cliente_por_defecto()
        self._dormir = dormir
        self._listados: dict[str, tuple[float, list[dict]]] = {}

    # --- HTTP ---

    @staticmethod
    def _es_limitacion(respuesta: httpx.Response) -> bool:
        """429, o 403 con motivo de rate limit (Drive usa los dos)."""
        if respuesta.status_code == 429:
            return True
        if respuesta.status_code != 403:
            return False
        try:
            errores = respuesta.json().get("error", {}).get("errors", [])
        except ValueError:
            return False
        motivos = {e.get("reason") for e in errores if isinstance(e, dict)}
        return bool(motivos & {"rateLimitExceeded", "userRateLimitExceeded"})

    @staticmethod
    def _detalle(respuesta: httpx.Response) -> str:
        """Mensaje de error de Drive sin volcar el cuerpo entero."""
        try:
            mensaje = respuesta.json().get("error", {}).get("message")
        except ValueError:
            return ""
        return mensaje if isinstance(mensaje, str) else ""

    @staticmethod
    def _error(respuesta: httpx.Response) -> Exception:
        """Traduce una respuesta fallida a la excepción que corresponde."""
        if respuesta.status_code == 401:
            return TokenVencido("la sesión con Google venció: volvé a conectar tu cuenta")
        if respuesta.status_code == 404:
            return NoEncontradoEnDrive("Drive no encuentra el archivo pedido")
        detalle = ClienteDrive._detalle(respuesta)
        texto = f": {detalle}" if detalle else ""
        return ErrorDrive(f"Google Drive respondió HTTP {respuesta.status_code}{texto}")

    def _solicitar(self, metodo: str, url: str, **kwargs) -> httpx.Response:
        """Petición con backoff exponencial ante límite de cuota.

        Nada de esto corre en el event loop: los endpoints que lo usan
        son `def`, así que FastAPI los ejecuta en el threadpool y
        `time.sleep` no congela el servidor (regla 3 de la skill).
        """
        headers = dict(kwargs.pop("headers", None) or {})
        headers["Authorization"] = f"Bearer {self._token()}"
        ultimo_error: httpx.Response | None = None

        for intento in range(TOPE_REINTENTOS):
            try:
                respuesta = self._http.request(metodo, url, headers=headers, **kwargs)
            except httpx.HTTPError as exc:
                logger.warning("no se pudo contactar con Google Drive: %s", exc)
                raise ErrorDrive(f"no se pudo contactar con Google Drive: {exc}") from exc
            if not self._es_limitacion(respuesta):
                if respuesta.status_code >= 400:
                    raise self._error(respuesta)
                return respuesta
            ultimo_error = respuesta
            espera = min(2**intento, 8) + random.uniform(0, 0.5)
            logger.warning(
                "Drive limitó la petición (HTTP %s), reintento %d/%d en %.1fs",
                respuesta.status_code,
                intento + 1,
                TOPE_REINTENTOS,
                espera,
            )
            self._dormir(espera)

        assert ultimo_error is not None
        raise ErrorDrive(
            f"Google Drive siguió limitando peticiones tras {TOPE_REINTENTOS} reintentos"
        )

    # --- Operaciones ---

    def listar(self, carpeta: str) -> list[dict]:
        """Hijos directos de una carpeta, paginados y cacheados.

        Siempre se manda `spaces=appDataFolder`: ahí vive todo lo de
        PurpleMD y el valor por defecto de `spaces` es `drive`, con el que
        una búsqueda por `parents` dentro de la carpeta oculta vuelve
        vacía («To search for files in the application data folder, set
        the `spaces` field to `appDataFolder`», guía oficial de Google).
        """
        guardado = self._listados.get(carpeta)
        ahora = time.time()
        if guardado is not None and guardado[0] > ahora:
            return guardado[1]

        items: list[dict] = []
        pagina: str | None = None
        while True:
            params: dict[str, str] = {
                "q": f"'{carpeta}' in parents and trashed = false",
                "spaces": ESPACIO,
                "pageSize": str(TOPE_PAGINA),
                "fields": CAMPOS_LISTA,
            }
            if pagina:
                params["pageToken"] = pagina
            datos = self._solicitar("GET", f"{API}/files", params=params).json()
            items.extend(datos.get("files", []))
            pagina = datos.get("nextPageToken")
            if not pagina:
                break

        self._listados[carpeta] = (ahora + TTL_LISTADO_SEG, items)
        return items

    def buscar_raiz(self) -> str | None:
        """Carpeta `projects` dentro de `appDataFolder`, si ya existe.

        La query la acota a `spaces=appDataFolder` y a los hijos
        directos: una carpeta de proyecto llamada «projects» vive una
        capa más abajo y no puede confundirse con la raíz.

        **Orden total y determinista.** Si hay más de una raíz —lo que
        solo puede venir de una carrera entre dos `crear_raiz()`— hay que
        elegir la **misma** siempre: Drive no promete el orden de los
        resultados sin `orderBy`, y una raíz que cambiara entre una
        petición y la siguiente repartiría los proyectos entre dos árboles
        distintos. Se pide `orderBy=createdTime` y, como `createdTime`
        podría empatar al segundo, se desempata con el `id`, que es único.
        """
        respuesta = self._solicitar(
            "GET",
            f"{API}/files",
            params={
                "q": (
                    f"name = '{RAIZ}' and mimeType = '{MIME_CARPETA}' "
                    f"and '{ESPACIO}' in parents and trashed = false"
                ),
                "spaces": ESPACIO,
                "pageSize": "10",
                "fields": "files(id,createdTime)",
                "orderBy": "createdTime",
            },
        )
        encontradas = respuesta.json().get("files", [])
        if len(encontradas) > 1:
            logger.warning("hay %d carpetas «%s» en appDataFolder; elijo la más vieja",
                           len(encontradas), RAIZ)
        encontradas.sort(key=lambda f: (f.get("createdTime") or "", f["id"]))
        return encontradas[0]["id"] if encontradas else None

    def crear_raiz(self) -> dict:
        """Crea la carpeta `projects` en `appDataFolder`.

        `parents: ["appDataFolder"]` es la forma documentada de apuntar a
        la carpeta oculta de la app; Drive la materializa al primer
        archivo que se crea ahí dentro.
        """
        return self._post_meta(
            {"name": RAIZ, "mimeType": MIME_CARPETA, "parents": [ESPACIO]}
        )

    def _post_meta(self, cuerpo: dict) -> dict:
        return self._solicitar(
            "POST", f"{API}/files", json=cuerpo, params={"fields": CAMPOS_META}
        ).json()

    def crear_carpeta(self, nombre: str, padre: str) -> dict:
        return self._post_meta(
            {"name": nombre, "mimeType": MIME_CARPETA, "parents": [padre]}
        )

    def meta(self, identificador: str) -> dict:
        return self._solicitar(
            "GET", f"{API}/files/{identificador}", params={"fields": CAMPOS_META}
        ).json()

    def renombrar(self, identificador: str, nombre: str, descripcion: str | None = None) -> dict:
        cuerpo: dict = {"name": nombre}
        if descripcion is not None:
            cuerpo["description"] = descripcion
        return self._solicitar(
            "PATCH",
            f"{API}/files/{identificador}",
            json=cuerpo,
            params={"fields": CAMPOS_META},
        ).json()

    def tocar(self, identificador: str, epoch: float) -> dict:
        """Guarda un epoch en la `description` para que el proyecto «se mueva»."""
        return self._solicitar(
            "PATCH",
            f"{API}/files/{identificador}",
            json={"description": str(int(epoch))},
            params={"fields": CAMPOS_META},
        ).json()

    def mover(
        self, identificador: str, nombre: str, padre_nuevo: str, padre_viejo: str
    ) -> dict:
        params: dict[str, str] = {"fields": CAMPOS_META}
        if padre_nuevo != padre_viejo:
            # `addParents`/`removeParents` mueven sin copiar ni borrar.
            params["addParents"] = padre_nuevo
            params["removeParents"] = padre_viejo
        return self._solicitar(
            "PATCH", f"{API}/files/{identificador}", json={"name": nombre}, params=params
        ).json()

    def subir(self, identificador: str, contenido: str) -> dict:
        """Reemplaza el contenido de un archivo (`uploadType=media`)."""
        return self._solicitar(
            "PATCH",
            f"{API_SUBIDA}/files/{identificador}",
            params={"uploadType": "media"},
            content=contenido.encode("utf-8"),
            headers={"Content-Type": MIME_TEXTO},
        ).json()

    def crear_archivo(self, nombre: str, padre: str, contenido: str) -> dict:
        """Crea un archivo con contenido en dos pasos.

        `uploadType=media` no admite metadatos y `uploadType=multipart`
        exige `multipart/related` a mano; los dos pasos (metadatos y
        después contenido) son más simples y cualquiera de los dos es un
        request estándar. Si el segundo falla, el primero se deshace para
        no dejar notas vacías colgando.
        """
        item = self._post_meta(
            {"name": nombre, "mimeType": _EXT_MIME, "parents": [padre]}
        )
        try:
            return self.subir(item["id"], contenido)
        except ErrorDrive:
            self.borrar_suave(item["id"])
            raise

    def leer(self, identificador: str) -> bytes:
        """Descarga el contenido crudo de un archivo."""
        return self._solicitar(
            "GET", f"{API}/files/{identificador}", params={"alt": "media"}
        ).content

    def borrar(self, identificador: str) -> None:
        """Borra **permanentemente**: no se recicla en la papelera.

        Dejarlo en la papelera consumiría cuota del usuario y no sería
        un borrado para el contrato de `eliminar_proyecto` (204, sin
        vuelta atrás).
        """
        self._solicitar("DELETE", f"{API}/files/{identificador}")

    def borrar_suave(self, identificador: str) -> None:
        """Borra ignorando el resultado: se usa para deshacer creaciones."""
        try:
            self.borrar(identificador)
        except ErrorDrive as exc:
            logger.warning("no pude deshacer la creación de %s: %s", identificador, exc)

    def eliminar_recursivo(self, identificador: str) -> None:
        """Borra una carpeta con todo su contenido."""
        for item in self.listar(identificador):
            if item["mimeType"] == MIME_CARPETA:
                self.eliminar_recursivo(item["id"])
            else:
                self.borrar(item["id"])
        self.borrar(identificador)

    def token_vigente(self) -> str:
        """Fuerza la obtención del token: es la comprobación de `/health`."""
        return self._token()

    def invalidar_listados(self) -> None:
        """Olvida los listados cacheados tras una escritura."""
        self._listados.clear()


class DriveStorage:
    """Implementación de `Storage` sobre el Drive del usuario."""

    def __init__(self, cliente: ClienteDrive) -> None:
        self._cliente = cliente
        self._ids: dict[str, str] = {}

    # --- Resolución de rutas ---

    def _invalidar(self) -> None:
        self._cliente.invalidar_listados()

    def _id_carpeta(self, ruta: str, *, crear: bool = False) -> str | None:
        """ID de la carpeta lógica `ruta`; `""` es la raíz `projects`.

        Devuelve `None` si no existe y `crear` es falso. Las carpetas
        intermedias se crean solo cuando `crear` es true, que es lo que
        permite distinguir «no existe la carpeta» (404) de «falta la
        carpeta intermedia» (se crea, como hace el backend local).
        """
        if ruta in self._ids:
            return self._ids[ruta]

        if ruta == "":
            identificador = self._cliente.buscar_raiz()
            if identificador is None and crear:
                identificador = self._cliente.crear_raiz()["id"]
                self._invalidar()
        else:
            padre = self._id_carpeta(_ruta_del_proyecto(ruta), crear=crear)
            if padre is None:
                return None
            identificador = self._hijo_carpeta(padre, _segmento(ruta))
            if identificador is None and crear:
                identificador = self._cliente.crear_carpeta(_segmento(ruta), padre)["id"]
                self._invalidar()

        if identificador:
            self._ids[ruta] = identificador
        return identificador

    def _hijo_carpeta(self, padre: str, nombre: str) -> str | None:
        """ID de la subcarpeta `nombre`, o `None` si no existe."""
        candidatas = [
            item["id"]
            for item in self._cliente.listar(padre)
            if item["mimeType"] == MIME_CARPETA and item["name"] == nombre
        ]
        if len(candidatas) > 1:
            logger.warning(
                "Drive devuelve %d carpetas %r en el mismo padre; uso la primera",
                len(candidatas),
                nombre,
            )
        return candidatas[0] if candidatas else None

    def _archivo_en(self, carpeta: str, nombre: str) -> dict | None:
        """Archivo `nombre` dentro de `carpeta`, o `None`."""
        candidatos = [
            item
            for item in self._cliente.listar(carpeta)
            if item["mimeType"] != MIME_CARPETA and item["name"] == nombre
        ]
        if len(candidatos) > 1:
            logger.warning(
                "Drive devuelve %d archivos %r en el mismo padre; uso el primero",
                len(candidatos),
                nombre,
            )
        return candidatos[0] if candidatos else None

    def _proyecto(self, nombre: str) -> str:
        """ID del proyecto o `ProyectoNoExiste`."""
        identificador = self._id_carpeta(nombre)
        if identificador is None:
            raise ProyectoNoExiste(f"no existe el proyecto {nombre!r}")
        return identificador

    def _carpeta_de_nota(self, proyecto: str, logica: str, *, crear: bool) -> str | None:
        """Carpeta que contiene la nota `logica` dentro de `proyecto`."""
        base = self._id_carpeta(proyecto, crear=crear)
        if base is None:
            return None
        intermedias = _ruta_del_proyecto(logica)
        if not intermedias:
            return base
        return self._id_carpeta(f"{proyecto}/{intermedias}", crear=crear)

    @staticmethod
    def _verificar_tamano(content: str) -> None:
        tamano = len(content.encode("utf-8"))
        if tamano > MAX_BYTES:
            raise NotaDemasiadoGrande(f"la nota ocupa {tamano} bytes y el máximo es {MAX_BYTES}")

    @staticmethod
    def _nombre_archivo(logica: str) -> str:
        return f"{_segmento(logica)}{EXTENSION}"

    def _tocar(self, proyecto: str) -> None:
        """Actualiza la marca de modificación de la **carpeta del proyecto**.

        La marca va en el proyecto y no en lo que se tocó: Drive no mueve
        el `modifiedTime` de una carpeta cuando cambian sus hijos, así
        que una nota guardada dejaría la lista de proyectos con la fecha
        vieja. De paso, resolverla acá en vez de recibir el `item` del
        llamado evita equivocarse de `id` (se mandaba el de la nota).

        Un fallo acá no puede tirarse abajo una escritura que ya salió
        bien: se registra y el proyecto queda con su marca vieja.
        """
        try:
            identificador = self._id_carpeta(proyecto)
            if identificador is None:
                return
            self._cliente.tocar(identificador, time.time())
        except ErrorDrive as exc:
            logger.warning("no pude actualizar la marca de %r: %s", proyecto, exc)

    # --- Protocolo Storage ---

    def listar_proyectos(self) -> list[Proyecto]:
        """Proyectos ordenados por su última modificación, descendente."""
        raiz = self._id_carpeta("")
        if raiz is None:
            return []
        proyectos = []
        for item in self._cliente.listar(raiz):
            if item["mimeType"] != MIME_CARPETA or not _nombre_valido(item["name"]):
                continue
            proyectos.append(Proyecto(name=item["name"], modified=_modificado(item)))
        proyectos.sort(key=lambda proyecto: proyecto.modified, reverse=True)
        return proyectos

    def crear_proyecto(self, name: str) -> Proyecto:
        nombre = validar_nombre(name)
        raiz = self._id_carpeta("", crear=True)
        if raiz is None:  # pragma: no cover - la raíz se crea sola
            raise ErrorDrive("no se pudo crear la carpeta de proyectos en Drive")
        if self._hijo_carpeta(raiz, nombre) is not None:
            raise ProyectoYaExiste(f"ya existe el proyecto {nombre!r}")
        item = self._cliente.crear_carpeta(nombre, raiz)
        self._invalidar()
        return Proyecto(name=nombre, modified=_modificado(item))

    def renombrar_proyecto(self, name: str, nuevo: str) -> Proyecto:
        nombre = validar_nombre(name)
        nuevo_nombre = validar_nombre(nuevo)
        identificador = self._proyecto(nombre)
        raiz = self._id_carpeta("")
        if nuevo_nombre == nombre:
            return Proyecto(name=nombre, modified=_modificado(self._cliente.meta(identificador)))
        if raiz is not None and self._hijo_carpeta(raiz, nuevo_nombre) is not None:
            raise ProyectoYaExiste(f"ya existe el proyecto {nuevo_nombre!r}")
        marca = str(int(time.time()))
        item = self._cliente.renombrar(identificador, nuevo_nombre, descripcion=marca)
        self._ids.pop(nombre, None)
        self._invalidar()
        return Proyecto(name=nuevo_nombre, modified=_modificado(item))

    def eliminar_proyecto(self, name: str) -> None:
        nombre = validar_nombre(name)
        self._cliente.eliminar_recursivo(self._proyecto(nombre))
        self._ids.clear()
        self._invalidar()

    def arbol_proyecto(self, proyecto: str) -> Arbol:
        nombre = validar_nombre(proyecto)
        carpetas: list[Entrada] = []
        notas: list[Entrada] = []
        # Prefijo vacío: las rutas del árbol son relativas al proyecto,
        # igual que en los otros dos backends. Empezar acá con el nombre
        # del proyecto devolvía `proyecto/carpeta` y rompía el export.
        self._recorrer(self._proyecto(nombre), "", carpetas, notas)
        carpetas.sort(key=lambda entrada: entrada.path)
        notas.sort(key=lambda entrada: entrada.path)
        return Arbol(project=nombre, entries=[*carpetas, *notas])

    def _recorrer(
        self, carpeta: str, prefijo: str, carpetas: list[Entrada], notas: list[Entrada]
    ) -> None:
        """Junta carpetas y notas de `carpeta` (y sus subcarpetas)."""
        for item in self._cliente.listar(carpeta):
            nombre = item["name"]
            relativa = f"{prefijo}/{nombre}" if prefijo else nombre
            if item["mimeType"] == MIME_CARPETA:
                if not _nombre_valido(nombre):
                    continue
                carpetas.append(Entrada(type="dir", path=relativa, modified=_modificado(item)))
                self._recorrer(item["id"], relativa, carpetas, notas)
            elif nombre.endswith(EXTENSION) and _nombre_valido(nombre[: -len(EXTENSION)]):
                notas.append(
                    Entrada(
                        type="note",
                        path=relativa[: -len(EXTENSION)],
                        modified=_modificado(item),
                    )
                )

    def leer_nota(self, proyecto: str, ruta: str) -> Nota:
        nombre = validar_nombre(proyecto)
        logica = validar_ruta(ruta)
        self._proyecto(nombre)
        carpeta = self._carpeta_de_nota(nombre, logica, crear=False)
        archivo = self._archivo_en(carpeta, self._nombre_archivo(logica)) if carpeta else None
        if archivo is None:
            raise NotaNoEncontrada(f"no existe la nota {logica!r} en el proyecto {nombre!r}")
        contenido = self._cliente.leer(archivo["id"]).decode("utf-8")
        return Nota(
            project=nombre, path=logica, content=contenido, modified=_modificado(archivo)
        )

    def crear_nota(self, proyecto: str, ruta: str, content: str) -> Nota:
        nombre = validar_nombre(proyecto)
        logica = validar_ruta(ruta)
        self._verificar_tamano(content)
        if self._id_carpeta(nombre) is None:
            raise ProyectoNoExiste(f"no existe el proyecto {nombre!r}")
        carpeta = self._carpeta_de_nota(nombre, logica, crear=True)
        if carpeta is None:  # pragma: no cover - la raíz del proyecto existe
            raise ProyectoNoExiste(f"no existe el proyecto {nombre!r}")
        archivo_nombre = self._nombre_archivo(logica)
        if self._archivo_en(carpeta, archivo_nombre) is not None:
            raise NotaYaExiste(f"ya existe la nota {logica!r} en el proyecto {nombre!r}")
        item = self._cliente.crear_archivo(archivo_nombre, carpeta, content)
        self._invalidar()
        self._tocar(nombre)
        return Nota(project=nombre, path=logica, content=content, modified=_modificado(item))

    def guardar_nota(self, proyecto: str, ruta: str, content: str) -> Nota:
        nombre = validar_nombre(proyecto)
        logica = validar_ruta(ruta)
        self._verificar_tamano(content)
        if self._id_carpeta(nombre) is None:
            raise ProyectoNoExiste(f"no existe el proyecto {nombre!r}")
        carpeta = self._carpeta_de_nota(nombre, logica, crear=False)
        archivo_nombre = self._nombre_archivo(logica)
        archivo = self._archivo_en(carpeta, archivo_nombre) if carpeta else None
        if archivo is None:
            raise NotaNoEncontrada(f"no existe la nota {logica!r} en el proyecto {nombre!r}")
        item = self._cliente.subir(archivo["id"], content)
        self._invalidar()
        self._tocar(nombre)
        return Nota(project=nombre, path=logica, content=content, modified=_modificado(item))

    def renombrar_nota(self, proyecto: str, ruta: str, nuevo: str) -> Nota:
        logica = validar_ruta(ruta)
        segmento = validar_nombre(nuevo)
        return self.mover_nota(proyecto, logica, self._mismo_directorio(logica, segmento))

    @staticmethod
    def _mismo_directorio(ruta: str, nombre: str) -> str:
        padre, _, _ = ruta.rpartition("/")
        return f"{padre}/{nombre}" if padre else nombre

    @staticmethod
    def _dentro_de(ruta: str, carpeta: str) -> bool:
        return ruta.startswith(f"{carpeta}/")

    def mover_nota(self, proyecto: str, ruta: str, destino: str) -> Nota:
        nombre = validar_nombre(proyecto)
        origen_logica = validar_ruta(ruta)
        destino_logica = validar_ruta(destino)
        if self._id_carpeta(nombre) is None:
            raise ProyectoNoExiste(f"no existe el proyecto {nombre!r}")

        origen_carpeta = self._carpeta_de_nota(nombre, origen_logica, crear=False)
        origen_archivo = self._nombre_archivo(origen_logica)
        origen = (
            self._archivo_en(origen_carpeta, origen_archivo) if origen_carpeta else None
        )
        if origen_carpeta is None or origen is None:
            raise NotaNoEncontrada(
                f"no existe la nota {origen_logica!r} en el proyecto {nombre!r}"
            )
        if destino_logica == origen_logica:
            return Nota(
                project=nombre,
                path=origen_logica,
                content=self._cliente.leer(origen["id"]).decode("utf-8"),
                modified=_modificado(origen),
            )

        destino_carpeta = self._carpeta_de_nota(nombre, destino_logica, crear=True)
        if destino_carpeta is None:  # pragma: no cover - el proyecto existe
            raise ProyectoNoExiste(f"no existe el proyecto {nombre!r}")
        destino_archivo = self._nombre_archivo(destino_logica)
        if self._archivo_en(destino_carpeta, destino_archivo) is not None:
            raise DestinoOcupado(f"ya existe una nota en la ruta destino {destino_logica!r}")

        item = self._cliente.mover(origen["id"], destino_archivo, destino_carpeta, origen_carpeta)
        self._invalidar()
        self._tocar(nombre)
        contenido = self._cliente.leer(item["id"]).decode("utf-8")
        return Nota(
            project=nombre,
            path=destino_logica,
            content=contenido,
            modified=_modificado(item),
        )

    def eliminar_nota(self, proyecto: str, ruta: str) -> None:
        nombre = validar_nombre(proyecto)
        logica = validar_ruta(ruta)
        if self._id_carpeta(nombre) is None:
            raise ProyectoNoExiste(f"no existe el proyecto {nombre!r}")
        carpeta = self._carpeta_de_nota(nombre, logica, crear=False)
        archivo = self._archivo_en(carpeta, self._nombre_archivo(logica)) if carpeta else None
        if archivo is None:
            raise NotaNoEncontrada(f"no existe la nota {logica!r} en el proyecto {nombre!r}")
        self._cliente.borrar(archivo["id"])
        self._invalidar()
        self._tocar(nombre)

    def renombrar_directorio(self, proyecto: str, ruta: str, nuevo: str) -> Directorio:
        logica = validar_ruta(ruta)
        segmento = validar_nombre(nuevo)
        return self.mover_directorio(
            proyecto, logica, self._mismo_directorio(logica, segmento)
        )

    def mover_directorio(self, proyecto: str, ruta: str, destino: str) -> Directorio:
        nombre = validar_nombre(proyecto)
        origen_logica = validar_ruta(ruta)
        destino_logica = validar_ruta(destino)
        if self._id_carpeta(nombre) is None:
            raise ProyectoNoExiste(f"no existe el proyecto {nombre!r}")

        origen = self._id_carpeta(f"{nombre}/{origen_logica}")
        if origen is None:
            raise DirectorioNoEncontrado(
                f"no existe el directorio {origen_logica!r} en el proyecto {nombre!r}"
            )
        if destino_logica == origen_logica:
            return Directorio(
                project=nombre, path=origen_logica, modified=_modificado(self._cliente.meta(origen))
            )

        dentro = self._dentro_de(destino_logica, origen_logica) or self._dentro_de(
            origen_logica, destino_logica
        )
        if dentro:
            raise MovimientoInvalido(
                f"no se puede mover el directorio {origen_logica!r} hacia {destino_logica!r}: "
                "una ruta contiene a la otra"
            )

        padre_origen = f"{nombre}/{_ruta_del_proyecto(origen_logica)}" if _ruta_del_proyecto(
            origen_logica
        ) else nombre
        padre_destino = f"{nombre}/{_ruta_del_proyecto(destino_logica)}" if _ruta_del_proyecto(
            destino_logica
        ) else nombre

        id_padre_origen = self._id_carpeta(padre_origen)
        id_padre_destino = self._id_carpeta(padre_destino, crear=True)
        if id_padre_origen is None or id_padre_destino is None:  # pragma: no cover
            raise ProyectoNoExiste(f"no existe el proyecto {nombre!r}")

        if self._hijo_carpeta(id_padre_destino, _segmento(destino_logica)) is not None:
            raise DestinoOcupado(
                f"ya existe un directorio en la ruta destino {destino_logica!r}"
            )

        item = self._cliente.mover(
            origen, _segmento(destino_logica), id_padre_destino, id_padre_origen
        )
        self._ids.pop(f"{nombre}/{origen_logica}", None)
        self._invalidar()
        self._tocar(nombre)
        return Directorio(
            project=nombre, path=destino_logica, modified=_modificado(item)
        )

    def eliminar_directorio(self, proyecto: str, ruta: str, recursive: bool = False) -> None:
        nombre = validar_nombre(proyecto)
        logica = validar_ruta(ruta)
        if self._id_carpeta(nombre) is None:
            raise ProyectoNoExiste(f"no existe el proyecto {nombre!r}")
        identificador = self._id_carpeta(f"{nombre}/{logica}")
        if identificador is None:
            raise DirectorioNoEncontrado(
                f"no existe el directorio {logica!r} en el proyecto {nombre!r}"
            )
        if recursive:
            self._cliente.eliminar_recursivo(identificador)
        elif self._cliente.listar(identificador):
            raise DirectorioNoVacio(
                f"el directorio {logica!r} no está vacío; "
                "se necesita recursive=true para borrarlo con todo su contenido"
            )
        else:
            self._cliente.borrar(identificador)
        self._ids.pop(f"{nombre}/{logica}", None)
        self._invalidar()
        self._tocar(nombre)

    def esta_operativo(self) -> bool:
        """¿Hay un token de Drive utilizable?

        No hace una llamada a la red: `/health` se consulta cada pocos
        segundos desde el HEALTHCHECK del contenedor y cada chequeo
        costaría 100 unidades de cuota. Un token que no se puede
        refrescar ya deja el backend degradado, y un fallo de red se
        ve en la primera operación real.
        """
        try:
            self._cliente.token_vigente()
        except Exception as exc:
            logger.warning("el backend de Drive no está operativo: %s", exc)
            return False
        return True

    def exportar_proyecto(self, proyecto: str) -> bytes:
        """Exporta un proyecto completo como bytes ZIP."""
        import zipfile
        from io import BytesIO

        nombre = validar_nombre(proyecto)
        self._proyecto(nombre)

        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            meta = {
                "project": nombre,
                "exported_at": datetime.now(UTC).isoformat(),
                "version": 1,
            }
            zf.writestr(".purplemd.json", json.dumps(meta, ensure_ascii=False, indent=2))
            for entrada in self.arbol_proyecto(nombre).entries:
                if entrada.type == "note":
                    contenido = self.leer_nota(nombre, entrada.path).content
                    zf.writestr(f"{entrada.path}{EXTENSION}", contenido)
        return buffer.getvalue()

    def importar_proyecto(self, proyecto: str, zip_bytes: bytes) -> dict:
        """Importa un proyecto desde bytes ZIP, creando carpetas al pasar."""
        nombre = validar_nombre(proyecto)
        if self._id_carpeta(nombre, crear=True) is None:  # pragma: no cover
            raise ErrorDrive("no se pudo crear el proyecto en Drive")

        lectura = leer_notas_zip(zip_bytes)
        resultado = lectura.resultado
        if lectura.abortar:
            return resultado

        for ruta_logica, contenido in lectura.notas:
            try:
                carpeta = self._carpeta_de_nota(nombre, ruta_logica, crear=True)
                if carpeta is None:
                    raise ProyectoNoExiste(f"no existe el proyecto {nombre!r}")
                archivo_nombre = self._nombre_archivo(ruta_logica)
                existente = self._archivo_en(carpeta, archivo_nombre)
                if existente is None:
                    self._cliente.crear_archivo(archivo_nombre, carpeta, contenido)
                    resultado["creadas"] += 1
                else:
                    self._cliente.subir(existente["id"], contenido)
                    resultado["actualizadas"] += 1
                self._invalidar()
            except Exception as exc:
                resultado["omitidas"] += 1
                resultado["errores"].append({
                    "path": ruta_logica,
                    "motivo": f"error interno: {exc}",
                })

        self._tocar(nombre)
        return resultado
