#!/usr/bin/env python3
"""API HTTP de purplemd: editor de markdown mínimo con FastAPI.

Organiza todo en proyectos: cada proyecto es un directorio bajo
`{PURPLEMD_DIR}/projects/` y cada nota un archivo `*.md` dentro, con
subcarpetas recursivas (persistencia vía `purplemd`) y convierte markdown a
HTML (vía `renderer`). Qué expone cada endpoint:

- `GET /` sirve el frontend (`static/index.html`) y `GET /static/{ruta:path}`
  su CSS y JS (montado con StaticFiles).
- `GET /api/projects` lista `{name, modified}` de los proyectos, del más
  reciente al más antiguo, y `POST /api/projects` crea uno (201; 409 si ya
  existe; 422 si el nombre no sirve).
- `PATCH /api/projects/{project}` renombra un proyecto (200 con
  `{name, modified}`; 404 si no existe; 409 si ya hay otro proyecto con ese
  nombre; 422 si el nombre no sirve; renombrar al mismo nombre es 200
  idempotente) y `DELETE /api/projects/{project}` lo borra recursivamente
  con todo su contenido (204 sin cuerpo; 404).
- `GET /api/projects/{project}/tree` devuelve el árbol recursivo del
  proyecto: primero las carpetas y después las notas, cada grupo en orden
  alfabético (404 si no existe el proyecto; 422 si el nombre no sirve).
- `POST /api/projects/{project}/notes` crea una nota en la ruta indicada y
  crea las carpetas intermedias que falten (201; 404 si no existe el
  proyecto; 409 si la nota ya existe; 422 si la ruta o el contenido no
  sirven: fuera de tope o con byte NUL).
- `GET /api/projects/{project}/notes/{path:path}` devuelve el detalle con
  contenido (404; 422) y `PUT` del mismo reemplaza el contenido (404; 422).
- `PATCH /api/projects/{project}/notes/{path:path}` mueve o renombra la nota
  a otra ruta relativa del mismo proyecto (200 con el detalle; 404; 409 si
  el destino está ocupado; 422 si la ruta destino no sirve o no se puede
  salir del proyecto; mover a la misma ruta es 200 idempotente) y `DELETE`
  del mismo borra la nota (204; 404).
- `PATCH /api/projects/{project}/dirs/{path:path}` mueve o renombra un
  directorio con todo su contenido (200 con `{project, path, modified}`;
  404; 409 si el destino está ocupado; 422 si la ruta no sirve o si el
  directorio terminaría dentro de sí mismo o de un ancestro; mover a la
  misma ruta es 200 idempotente) y `DELETE` del mismo lo borra: sin más
  debe estar vacío y con query `?recursive=true` borra todo su contenido
  (204; 404; 409 si no está vacío y no se pidió recursivo; 422).
- `POST /api/render` convierte markdown en HTML (422 si pasa 200 KB).
- `GET /health` reporta `{"estado": "ok" | "degradado"}` con HTTP 200
  siempre: el estado real vive en el body, no en el código HTTP.

Desarrollo local: uvicorn api:app --reload
"""

import hmac
import logging
import os  # noqa: F401 (usado en tests para patch)
import threading
import time
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import weasyprint
from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, ConfigDict, field_validator
from weasyprint.urls import URLFetcher

import purplemd
import renderer
from mcp_server import mcp, registrar_almacenamiento
from purplemd_auth import (
    COOKIE_OAUTH,
    COOKIE_SESION,
    TTL_OAUTH_SEG,
    TTL_SESION_SEG,
    TTL_TOKEN_MCP_SEG,
    ConfigAuth,
    Cuenta,
    LimiteCuentasError,
    OAuthError,
    almacen_de_entorno,
    cookie_segura,
    crear_token_mcp,
    desde_entorno,
    es_https,
    firmar,
    identificador_seguro,
    intercambiar_codigo,
    nuevo_state,
    nuevo_verifier,
    perfil,
    proveedor_vigente,
    url_autorizacion,
    verificar,
    verificar_token_mcp,
)
from purplemd_storage import (
    DIR_DEFECTO,
    MAX_IMPORT_ZIP_BYTES,
    ClienteDrive,
    DriveStorage,
    ErrorDrive,
    FilesystemStorage,
    MemoryStorage,
    NoEncontradoEnDrive,
    Storage,
    TokenVencido,
    get_storage,
)

# Tope de markdown para POST /api/render. El HTML renderizado puede pesar
# varios veces más que la entrada, y el parseo corre en el hilo del request:
# 200 KB bastan para cualquier nota real y evitan requests que cuelen el
# evento durante segundos.
MAX_RENDER_BYTES = 200 * 1024

# SSRF: WeasyPrint baja por su cuenta toda URL que aparezca en el HTML del
# PDF (imágenes remotas, `file://`, rutas relativas), lo que deja al servidor
# hablando con la red interna o leyendo disco en nombre de quien pidió el PDF.
# Este fetcher solo acepta `data:` (imágenes inline); el resto se rechaza
# antes de tocar la red y WeasyPrint omite el recurso sin romper el documento.
FETCHER_PDF = URLFetcher(allowed_protocols={"data"})

# Página del frontend servida en GET /. Se resuelve relativa a este archivo
# y no al cwd para que funcione igual desde cualquier directorio.
INDEX_HTML = Path(__file__).parent / "static" / "index.html"

# --- Sesión, storage por request y seguridad ---
#
# La integración con Google es opt-in: sin credenciales en el entorno,
# `_config().habilitado` es False y todo funciona como siempre (sin
# usuarios, sin cookie, la demo pública intacta). Cuando está encendida,
# la identidad decide **dónde** viven los datos y quién puede verlos.

# Cabeceras de seguridad (regla 6 de `skills/seguridad/SKILL.md`).
# La CSP no permite scripts ni estilos externos: el frontend no usa CDN.
CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data: https:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)
CABECERAS_SEGURIDAD = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
# Swagger y el transporte MCP traen su propio marcado: imponerles la CSP
# del frontend los rompería (Swagger carga su JS desde un CDN).
_RUTAS_SIN_CSP = ("/docs", "/redoc", "/openapi.json", "/mcp")

# Únicos /api/ que no exigen sesión: no tocan storage (ver
# `_seguridad_y_sesion`). Son lo que permite previsualizar y exportar a
# PDF en modo invitado, donde no hay cuenta y por tanto no hay storage.
_RUTAS_STATELESS = frozenset({"/api/render", "/api/pdf"})

# Verbo que un navegador puede disparar sin preflight; los demás llevan
# `Origin`, que es lo que el chequeo de CSRF mira.
_METODOS_SEGUROS = frozenset({"GET", "HEAD", "OPTIONS"})

# Tope de usuarios con backend en memoria a la vez: crecer sin límite es
# un DoS lento (regla 7 de la skill de seguridad).
TOPE_USUARIOS_MEMORIA = 64
_MEMORIA_USUARIOS: dict[str, MemoryStorage] = {}
_MEMORIA_CANDADO = threading.Lock()


def _config() -> ConfigAuth:
    """Configuración de Google vigente (se lee del entorno en cada request)."""
    return desde_entorno()


def _sesion(request: Request) -> dict | None:
    """Payload de la sesión de esta petición, o `None` si no hay.

    La cookie alterada, vencida o ausente devuelve `None`: nunca lanza.
    `sub` además es obligatorio, porque es lo que define el aislamiento:
    una sesión sin identificador no puede resolver un storage.
    """
    config = _config()
    if not config.habilitado:
        return None
    datos = verificar(request.cookies.get(COOKIE_SESION), config.secret_key)
    if datos is None:
        return None
    # Un token con alcance (el del MCP) no es una sesión: cada credencial
    # abre solo lo suyo, aunque compartan clave y formato.
    if datos.get("alcance") is not None:
        return None
    sub = datos.get("sub")
    if not isinstance(sub, str) or not sub:
        return None
    return datos


def _directorio_usuario(sub: str) -> Path:
    """Carpeta de datos de una cuenta cuando el backend es el filesystem.

    Sin sesión, PurpleMD escribe en `{PURPLEMD_DIR}/projects/`. Con
    sesión, en `{PURPLEMD_DIR}/users/{hash}/projects/`, con lo que dos
    cuentas no se pisan aunque compartan volumen. Los proyectos con el
    prefijo `u_xxxx_` de la era sin autenticación quedan donde estaban,
    fuera de toda carpeta de usuario (ver docs/AUTH.md).
    """
    return Path(os.environ.get("PURPLEMD_DIR", DIR_DEFECTO)) / "users" / identificador_seguro(sub)


def _memoria_por_usuario(sub: str) -> MemoryStorage:
    """Instancia de `MemoryStorage` por cuenta, con tope.

    El backend en memoria es efímero por diseño, así que perder estas
    instancias al reiniciar no es un problema nuevo.
    """
    clave = identificador_seguro(sub)
    with _MEMORIA_CANDADO:
        storage = _MEMORIA_USUARIOS.get(clave)
        if storage is not None:
            return storage
        if len(_MEMORIA_USUARIOS) >= TOPE_USUARIOS_MEMORIA:
            raise HTTPException(
                status_code=503,
                detail=f"hay {TOPE_USUARIOS_MEMORIA} sesiones en el backend en memoria",
            )
        storage = MemoryStorage()
        _MEMORIA_USUARIOS[clave] = storage
        return storage


def almacenamiento(request: Request) -> Storage:
    """Storage que corresponde a esta petición.

    - Sin integración Google: el backend de siempre (`PURPLEMD_STORAGE`).
    - Con Google y sesión: los datos de **ese** usuario, en su Drive o en
      su subdirectorio.
    - Con Google y sin sesión: 401 (el middleware ya lo habría cortado,
      pero esta función se expone sola en los tests).
    """
    config = _config()
    sesion = _sesion(request)

    if not config.habilitado:
        if os.environ.get("PURPLEMD_STORAGE", "").lower() == "drive":
            raise HTTPException(
                status_code=503,
                detail="PURPLEMD_STORAGE=drive necesita Google OAuth "
                "(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET y PURPLEMD_SECRET_KEY)",
            )
        return get_storage()

    if sesion is None:
        raise HTTPException(
            status_code=401, detail="sesión requerida: iniciá sesión con Google"
        )

    return _almacenamiento_de_sub(sesion["sub"])


def _almacenamiento_de_sub(sub: str) -> Storage:
    """Storage de una cuenta concreta: su carpeta, su memoria o su Drive.

    Lo comparten la API (que llega acá desde la sesión) y el servidor MCP
    (que llega desde su token): los dos caminos tienen que resolver el mismo
    destino, si no el aislamiento tendría dos definiciones distintas.
    """
    config = _config()
    backend = os.environ.get("PURPLEMD_STORAGE", "filesystem").lower()
    if backend == "drive":
        cuentas = almacen_de_entorno()
        return DriveStorage(ClienteDrive(proveedor_vigente(config, cuentas, sub)))
    if backend == "memory":
        return _memoria_por_usuario(sub)
    return FilesystemStorage(directorio=_directorio_usuario(sub))


class TokenMcpInvalido(Exception):  # noqa: N818 (nombre en español, como el resto)
    """Un tool del MCP llegó con un token que no identifica a nadie.

    El middleware lo corta antes de que el transporte MCP vea el request;
    llegar acá significa que el token se invocó fuera de ese filtro o que la
    cabecera cambió en el camino. Nunca se cae a otro storage.
    """


def almacenamiento_mcp(headers: Mapping[str, str] | None) -> Storage:
    """Storage que sirve a una herramienta del MCP (contrato en `mcp_server`).

    Cada mensaje MCP trae sus propias cabeceras, así que el token se
    revalida en cada tool: el middleware ya garantizó que el request era
    válido, pero esta función es la que decide **de quién** son los datos.

    - Sin login de Google: la raíz compartida de siempre (`get_storage`).
    - Con login: la carpeta (o el Drive) del `sub` que trae el token. El
      token estático del entorno no llega acá: no identifica a nadie.
    """
    config = _config()
    if not config.habilitado:
        return get_storage()
    token = (headers or {}).get("x-purplemd-token", "")
    payload = verificar_token_mcp(token, config.secret_key)
    if payload is None:
        logger.warning("tool del MCP con token inválido o ausente")
        raise TokenMcpInvalido("token de MCP inválido o vencido")
    return _almacenamiento_de_sub(payload["sub"])


# `mcp_server` define el contrato (cabeceras → storage) y no puede importar
# este módulo, que lo importa a él: la implementación se registra acá, al
# importar, antes de que uvicorn sirva el primer request.
registrar_almacenamiento(almacenamiento_mcp)


# Dependencia que FastAPI resuelve una vez por request y cachea: los
# endpoints la reciben como `almacen: StorageDep`.
StorageDep = Annotated[Storage, Depends(almacenamiento)]

# Logger del proceso, compartido con `renderer`. Los mensajes salen por el
# manejador raíz (stderr en uvicorn) y los tests los capturan con
# `assertLogs("purplemd")`. Todo 500 se registra con su traceback: responder
# un 500 sin dejar rastro hace imposible diagnosticar el fallo en producción.
logger = logging.getLogger("purplemd")

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield

app = FastAPI(
    title="purplemd",
    description=(
        "Editor de markdown ligero: notas en proyectos con subcarpetas y vista previa en HTML."
    ),
    lifespan=lifespan
)

mcp_security = TransportSecuritySettings(
    allowed_hosts=[
        "localhost",
        "localhost:*",
        "127.0.0.1",
        "127.0.0.1:*",
        "purplemd.onrender.com",
    ],
    allowed_origins=[
        "http://localhost:*",
        "http://127.0.0.1:*",
        "https://purplemd.onrender.com",
    ],
)

app.mount(
    "/mcp",
    mcp.streamable_http_app(
        streamable_http_path="/",
        transport_security=mcp_security,
    ),
)

# CORS: sin wildcards en orígenes, métodos ni cabeceras (regla 6 de
# `skills/seguridad/SKILL.md`). El frontend lo sirve la misma app en la
# raíz, así que en el uso normal las llamadas a `/api` son same-origin y
# CORS no interviene; esto es solo para consumidores externos de la API.
# `allow_credentials=True` hace que las cookies viajen, por eso el
# origen de producción va literal y la regex cubre únicamente localhost
# (el patrón que fija AGENTS.md).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://purplemd.onrender.com"],
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
    allow_credentials=True,
)


# Seguridad y sesión: un solo middleware para lo que aplica a cualquier
# ruta, incluidas las de los mounts (`/static`, `/mcp`). Corre por fuera
# del router, así que también cubre lo que se sirve ahí.
@app.middleware("http")
async def _seguridad_y_sesion(request: Request, call_next):
    """401 sin sesión, 403 con origen ajeno y cabeceras de seguridad.

    El chequeo de `Origin` es la segunda barrera de CSRF; la primera es
    la cookie `SameSite=Lax`, que el navegador no manda en peticiones
    cross-site. Solo se aplica con la integración Google encendida,
    que es cuando existe una sesión que valga la pena forging.
    """
    # El preflight lo resuelve CORS: cortarlo acá con un 401 dejaría al
    # navegador sin poder hacer la petición real.
    if request.method == "OPTIONS":
        return call_next(request)

    ruta = request.url.path
    config = _config()
    # El MCP se autentica con su propio token, no con la sesión, así que su
    # chequeo corre siempre —con o sin login de Google— y antes de todo lo
    # demás (ver `_rechazar_mcp`).
    if ruta.startswith("/mcp"):
        rechazo = _rechazar_mcp(request)
        if rechazo is not None:
            return rechazo
    if config.habilitado:
        if ruta.startswith("/api/") and not ruta.startswith("/api/auth/"):
            # `/api/render` y `/api/pdf` son stateless: reciben markdown y
            # devuelven HTML/PDF sin leer ni escribir storage. Por eso
            # pasan sin sesión — es lo que permite previsualizar y exportar
            # en modo invitado, donde no hay cuenta y, por tanto, no hay
            # storage. Sus topes de MAX_RENDER_BYTES siguen vigentes (los
            # cubre un test por endpoint).
            if ruta not in _RUTAS_STATELESS and _sesion(request) is None:
                return _respuesta_error(401, "sesión requerida: iniciá sesión con Google")
        if request.method not in _METODOS_SEGUROS and not _origen_propio(request):
            return _respuesta_error(403, "origen no permitido para esta operación")

    respuesta = await call_next(request)
    for nombre, valor in CABECERAS_SEGURIDAD.items():
        respuesta.headers.setdefault(nombre, valor)
    if not ruta.startswith(_RUTAS_SIN_CSP):
        respuesta.headers.setdefault("Content-Security-Policy", CSP)
    return respuesta


def _origen_propio(request: Request) -> bool:
    """¿El `Origin` del request es este mismo sitio?

    Sin `Origin` no se bloquea: `curl`, los tests y las descargas
    directas no lo mandan, y un navegador cross-site **siempre** lo manda
    (lo exige la especificación para las peticiones no simples), así que
    el hueco no es aprovechable desde un navegador.
    """
    origen = request.headers.get("origin")
    host = request.headers.get("host")
    if not origen or not host:
        return True
    try:
        partes = urlsplit(origen)
    except ValueError:
        return False
    return partes.scheme in {"http", "https"} and partes.netloc == host


def _rechazar_mcp(request: Request) -> JSONResponse | None:
    """El servidor MCP no tiene sesión de usuario: se autentica con su token.

    Dos regímenes, excluyentes entre sí:

    - **Con login de Google**: solo sirve un token firmado por cuenta
      (`alcance="mcp"`, con `sub`), el que emite `POST /api/auth/mcp-token`
      desde el menú de la app. Ese `sub` es el que después decide qué storage
      sirve cada tool. El token del entorno **no** vale acá: no identifica a
      nadie y lo único que alcanzaría sería la raíz de la era sin login.
    - **Sin login**: manda `PURPLEMD_MCP_TOKEN` por la cabecera
      `X-PurpleMD-Token`, recortado para que un `\n` de más al pegarlo no
      deje al cliente afuera. Sin esa variable, el MCP está apagado.

    `PURPLEMD_STORAGE=drive` ya no apaga el MCP: con token de cuenta se sirve
    el Drive de esa misma cuenta (ver `almacenamiento_mcp`). La única
    combinación que sigue apagada es drive **sin** credenciales de Google,
    que no tiene cuenta a la que pertenezca ese Drive.
    """
    recibido = request.headers.get("x-purplemd-token", "")
    config = _config()
    if config.habilitado:
        if not recibido:
            return _respuesta_error(
                403,
                "falta el token de MCP: generá el tuyo en la app "
                "(menú → Servidor MCP)",
            )
        if verificar_token_mcp(recibido, config.secret_key) is None:
            return _respuesta_error(401, "token de MCP inválido o vencido")
        return None

    if os.environ.get("PURPLEMD_STORAGE", "").lower() == "drive":
        # Sin credenciales de Google no hay cuenta a la que pertenezca ese
        # Drive y `get_storage()` lo sabe: mejor un 403 claro que una
        # excepción dentro del tool. Es el mismo caso que la API responde 503.
        return _respuesta_error(
            403,
            "el servidor MCP está deshabilitado con PURPLEMD_STORAGE=drive "
            "y sin credenciales de Google",
        )

    esperado = os.environ.get("PURPLEMD_MCP_TOKEN", "").strip()
    if not esperado:
        return _respuesta_error(
            403, "el servidor MCP está deshabilitado: falta PURPLEMD_MCP_TOKEN"
        )

    # Cabecera ausente (o vacía) → 403 con mensaje útil, no 401 genérico.
    if not recibido:
        return _respuesta_error(
            403,
            "falta el token de MCP: generá el tuyo en la app "
            "(menú → Servidor MCP)",
        )

    # Bytes y no str: `compare_digest` levanta con un valor no-ASCII, y una
    # cabecera arbitraria no tiene por qué serlo.
    if not hmac.compare_digest(recibido.encode("utf-8"), esperado.encode("utf-8")):
        return _respuesta_error(401, "token de MCP inválido")
    return None

# Montado como ruta (y no como router) para que /static/css/style.css y
# /static/js/app.js se sirvan sin escribir endpoints a mano.
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

# Plantillas de documentos: recursos .md en disco (no van embebidos en el
# frontend). El mount es solo lectura; la semilla del cliente los copia al
# proyecto «Plantillas» la primera vez. El `if` evita romper el arranque
# en instalaciones que no traen el directorio.
_PLANTILLAS = Path(__file__).parent / "plantillas"
if _PLANTILLAS.is_dir():
    app.mount("/plantillas", StaticFiles(directory=_PLANTILLAS, check_dir=True), name="plantillas")


class ProyectoCreacion(BaseModel):
    """Payload para crear un proyecto: solo el nombre lógico, sin extensión."""

    # extra="forbid": un campo mal escrito responde 422 en vez de
    # descartarse en silencio.
    model_config = ConfigDict(extra="forbid")

    name: str

    @field_validator("name")
    @classmethod
    def _validar_name(cls, value: str) -> str:
        """Aplica las reglas del núcleo al nombre del proyecto (422 si falla)."""
        try:
            return purplemd.validar_nombre(value)
        except purplemd.NombreInvalido as exc:
            raise ValueError(str(exc)) from exc


class ProyectoRenombre(BaseModel):
    """Payload para renombrar un proyecto: su nuevo nombre lógico."""

    model_config = ConfigDict(extra="forbid")

    name: str

    @field_validator("name")
    @classmethod
    def _validar_name(cls, value: str) -> str:
        """Aplica las reglas del núcleo al nombre nuevo (422 si falla)."""
        try:
            return purplemd.validar_nombre(value)
        except purplemd.NombreInvalido as exc:
            raise ValueError(str(exc)) from exc


class NotaCreacion(BaseModel):
    """Payload para crear una nota: ruta dentro del proyecto y contenido inicial."""

    model_config = ConfigDict(extra="forbid")

    path: str
    content: str

    @field_validator("path")
    @classmethod
    def _validar_path(cls, value: str) -> str:
        """Valida la ruta con las reglas del núcleo (422 si falla)."""
        try:
            return purplemd.validar_ruta(value)
        except purplemd.NombreInvalido as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("content")
    @classmethod
    def _validar_content(cls, value: str) -> str:
        """Valida el contenido como 422 de Pydantic: tope de tamaño y sin byte NUL."""
        return _validar_contenido(value)


class ActualizacionNota(BaseModel):
    """Payload para reemplazar el contenido de una nota existente."""

    model_config = ConfigDict(extra="forbid")

    content: str

    @field_validator("content")
    @classmethod
    def _validar_content(cls, value: str) -> str:
        """Valida el contenido como 422 de Pydantic: tope de tamaño y sin byte NUL."""
        return _validar_contenido(value)


class RutaNueva(BaseModel):
    """Payload para mover o renombrar una nota o un directorio.

    `path` es la nueva ruta relativa dentro del proyecto (puede cambiar de
    carpeta); sirve para los dos PATCH porque ambos consumen el mismo shape.
    """

    model_config = ConfigDict(extra="forbid")

    path: str

    @field_validator("path")
    @classmethod
    def _validar_path(cls, value: str) -> str:
        """Valida la ruta destino con las reglas del núcleo (422 si falla)."""
        try:
            return purplemd.validar_ruta(value)
        except purplemd.NombreInvalido as exc:
            raise ValueError(str(exc)) from exc


class RenderRequest(BaseModel):
    """Markdown a convertir en HTML para la vista previa."""

    model_config = ConfigDict(extra="forbid")

    markdown: str

    @field_validator("markdown")
    @classmethod
    def _validar_markdown(cls, value: str) -> str:
        """Acota la entrada a MAX_RENDER_BYTES (ver la constante)."""
        tamano = len(value.encode("utf-8"))
        if tamano > MAX_RENDER_BYTES:
            raise ValueError(
                f"el markdown ocupa {tamano} bytes y el máximo es {MAX_RENDER_BYTES}"
            )
        return value


class PdfRequest(RenderRequest):
    """Markdown a convertir en PDF, con el nombre del archivo de salida.

    Hereda de `RenderRequest` el tope de MAX_RENDER_BYTES: el PDF es tan
    costoso de componer como el render, no más, y repetir el validador
    solo serviría para que los dos topes pudieran divergir.
    """

    nombre: str = "nota"

    @field_validator("nombre")
    @classmethod
    def _validar_nombre_pdf(cls, value: str) -> str:
        """Fija la ruta de salida con las reglas del núcleo (422 si falla).

        `nombre` termina en la cabecera `Content-Disposition`, así que
        tiene que ser una ruta de verdad: `validar_ruta` valida cada
        segmento con `validar_nombre`, que no admite comillas, CR ni LF —
        lo que haría falta para inyectar una cabecera. Es la misma regla
        que aplica el PDF con storage, así los dos salen idénticos.
        """
        try:
            return purplemd.validar_ruta(value)
        except purplemd.NombreInvalido as exc:
            raise ValueError(str(exc)) from exc


class ProyectoSalida(BaseModel):
    """Proyecto con su fecha de modificación (epoch)."""

    name: str
    modified: float


class ListadoProyectos(BaseModel):
    """Listado de proyectos ordenado por modificación descendente."""

    projects: list[ProyectoSalida]


class EntradaArbol(BaseModel):
    """Entrada del árbol: subcarpeta o nota, con ruta relativa al proyecto."""

    type: Literal["dir", "note"]
    path: str
    modified: float


class ArbolProyecto(BaseModel):
    """Árbol recursivo de un proyecto: carpetas primero y notas después."""

    project: str
    entries: list[EntradaArbol]


class NotaSalida(BaseModel):
    """Detalle de una nota: proyecto, ruta relativa, contenido y modificación (epoch)."""

    project: str
    path: str
    content: str
    modified: float


class DirectorioSalida(BaseModel):
    """Directorio: proyecto, ruta relativa al proyecto y modificación (epoch)."""

    project: str
    path: str
    modified: float


class RenderResponse(BaseModel):
    """HTML resultante de convertir el markdown enviado."""

    html: str


class HealthResponse(BaseModel):
    """Estado del servicio: siempre HTTP 200, el estado real va en el body."""

    estado: Literal["ok", "degradado"]


def _validar_contenido(value: str) -> str:
    """Rechaza contenido que no sea texto plano, con mensaje en español.

    Cubre dos señales de que esto no es una nota markdown: pesar más de
    `purplemd.MAX_BYTES` y contener un byte NUL (`\\x00`), la señal clásica
    de un binario renombrado a `.md`. El cliente ya filtra binarios al
    importar, pero la API se puede pegar directo con `curl`, así que la
    defensa tiene que estar del lado del servidor.
    """
    if "\x00" in value:
        raise ValueError("el contenido no es texto plano: contiene un byte NUL (\\x00)")
    tamano = len(value.encode("utf-8"))
    if tamano > purplemd.MAX_BYTES:
        raise ValueError(
            f"el contenido ocupa {tamano} bytes y el máximo es {purplemd.MAX_BYTES}"
        )
    return value


def _salida(nota: purplemd.Nota) -> NotaSalida:
    """Adapta una Nota del núcleo al modelo de respuesta de la API."""
    return NotaSalida(
        project=nota.project,
        path=nota.path,
        content=nota.content,
        modified=nota.modified,
    )


def _respuesta_error(status_code: int, detalle: str) -> JSONResponse:
    """Error con el mismo formato `{"detail": ...}` que usa FastAPI."""
    return JSONResponse(status_code=status_code, content={"detail": detalle})


@app.exception_handler(purplemd.ProyectoNoExiste)
def _manejar_proyecto_inexistente(
    request: Request, exc: purplemd.ProyectoNoExiste
) -> JSONResponse:
    """Traduce el núcleo a 404 para el árbol y las notas de un proyecto ausente."""
    return _respuesta_error(404, str(exc))


@app.exception_handler(purplemd.NotaNoEncontrada)
def _manejar_no_encontrada(request: Request, exc: purplemd.NotaNoEncontrada) -> JSONResponse:
    """Traduce el núcleo a 404 para GET y PUT de notas inexistentes."""
    return _respuesta_error(404, str(exc))


@app.exception_handler(purplemd.ProyectoYaExiste)
def _manejar_proyecto_ya_existe(request: Request, exc: purplemd.ProyectoYaExiste) -> JSONResponse:
    """Traduce el núcleo a 409 para crear un proyecto que ya existe."""
    return _respuesta_error(409, str(exc))


@app.exception_handler(purplemd.NotaYaExiste)
def _manejar_ya_existe(request: Request, exc: purplemd.NotaYaExiste) -> JSONResponse:
    """Traduce el núcleo a 409 para crear una nota que ya existe."""
    return _respuesta_error(409, str(exc))


@app.exception_handler(purplemd.NombreInvalido)
def _manejar_nombre_invalido(request: Request, exc: purplemd.NombreInvalido) -> JSONResponse:
    """Traduce el núcleo a 422 (nombres llegados por path, no por Pydantic)."""
    return _respuesta_error(422, str(exc))


@app.exception_handler(purplemd.NotaDemasiadoGrande)
def _manejar_demasiado_grande(
    request: Request, exc: purplemd.NotaDemasiadoGrande
) -> JSONResponse:
    """Traduce el núcleo a 422; Pydantic ya cubre la mayoría de los casos."""
    return _respuesta_error(422, str(exc))


@app.exception_handler(purplemd.DirectorioNoEncontrado)
def _manejar_directorio_no_encontrado(
    request: Request, exc: purplemd.DirectorioNoEncontrado
) -> JSONResponse:
    """Traduce el núcleo a 404 para PATCH y DELETE de un directorio ausente."""
    return _respuesta_error(404, str(exc))


@app.exception_handler(purplemd.DestinoOcupado)
def _manejar_destino_ocupado(request: Request, exc: purplemd.DestinoOcupado) -> JSONResponse:
    """Traduce el núcleo a 409 para movimientos cuyo destino ya está ocupado."""
    return _respuesta_error(409, str(exc))


@app.exception_handler(purplemd.DirectorioNoVacio)
def _manejar_directorio_no_vacio(
    request: Request, exc: purplemd.DirectorioNoVacio
) -> JSONResponse:
    """Traduce el núcleo a 409 para DELETE de un directorio con contenido sin recursive."""
    return _respuesta_error(409, str(exc))


@app.exception_handler(purplemd.MovimientoInvalido)
def _manejar_movimiento_invalido(
    request: Request, exc: purplemd.MovimientoInvalido
) -> JSONResponse:
    """Traduce el núcleo a 422 para un directorio que se movería dentro de sí mismo."""
    return _respuesta_error(422, str(exc))


@app.exception_handler(Exception)
def _manejar_error_interno(request: Request, exc: Exception) -> JSONResponse:
    """Último recurso: 500 genérico, con el traceback en el log y sin
    exponer el stack ni datos internos en la respuesta."""
    logger.error("500 en %s %s", request.method, request.url.path, exc_info=exc)
    return _respuesta_error(500, "error interno al procesar la solicitud")


def _sesion_vencida(detalle: str) -> JSONResponse:
    """401 con la cookie de sesión borrada.

    Sirve tanto para «Google dejó de darnos token» como para «no hay
    sesión»: en los dos casos el camino de vuelta es el mismo, volver a
    conectar la cuenta, y dejar la cookie vieja solo haría bucles.
    """
    respuesta = _respuesta_error(401, detalle)
    respuesta.delete_cookie(COOKIE_SESION, path="/")
    return respuesta


@app.exception_handler(TokenVencido)
def _manejar_token_vencido(request: Request, exc: TokenVencido) -> JSONResponse:
    """401 cuando el token de Drive no se pudo refrescar (consentimiento revocado)."""
    logger.warning("token de Drive vencido en %s: %s", request.url.path, exc)
    return _sesion_vencida(str(exc))


@app.exception_handler(OAuthError)
def _manejar_oauth(request: Request, exc: OAuthError) -> JSONResponse:
    """401 cuando la credencial de Google ya no sirve."""
    logger.warning("fallo de OAuth en %s: %s", request.url.path, exc)
    return _sesion_vencida(str(exc))


@app.exception_handler(NoEncontradoEnDrive)
def _manejar_drive_404(request: Request, exc: NoEncontradoEnDrive) -> JSONResponse:
    """404 si el archivo desapareció de Drive entre el listado y el acceso."""
    return _respuesta_error(404, str(exc))


@app.exception_handler(ErrorDrive)
def _manejar_drive(request: Request, exc: ErrorDrive) -> JSONResponse:
    """503 para todo lo demás de Drive: cuota agotada, red o API caída.

    Es un estado transitorio del proveedor, no un error del pedido, y el
    detalle va al cliente para que pueda reintentar.
    """
    logger.error("Drive en %s %s", request.method, request.url.path, exc_info=exc)
    return _respuesta_error(503, str(exc))


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Sirve el frontend (index.html) tal cual está en disco.

    No aparece en /docs porque es solo el frontend, no un endpoint de datos.
    """
    return FileResponse(INDEX_HTML, media_type="text/html")


# --- Autenticación con Google (OAuth 2.0 + PKCE) ---
#
# Cuatro rutas, todas públicas (el middleware las salta porque empiezan
# con `/api/auth/`): el login redirige, el callback recibe, `me` le dice
# al frontend si hace falta entrar, y `logout` borra la sesión y los
# tokens guardados en el servidor.


def _destino_seguro(destino: str) -> str:
    """Solo rutas relativas de este mismo sitio.

    El `destino` viaja en una cookie firmada, pero firmada no significa
    inofensiva: si llegara `https://otro-sitio` el callback terminaría
    mandando al usuario a una página ajena con la cookie ya puesta.
    Se descarta todo lo que no sea una ruta interna.
    """
    if not destino.startswith("/") or destino.startswith("//") or "\\" in destino:
        return "/"
    return destino


def _redirect_uri(request: Request, config: ConfigAuth) -> str:
    """URI de redirección: la configurada, o la de este request."""
    return config.redirect_uri or str(request.url_for("callback_google"))


class SesionSalida(BaseModel):
    """Estado de la sesión, para que el frontend decida si muestra el login."""

    requiere_sesion: bool
    autenticado: bool
    email: str = ""
    name: str = ""
    picture: str = ""
    # `almacen` es el que dice la verdad: qué backend guarda los datos.
    almacen: str = "filesystem"


class TokenMcpSalida(BaseModel):
    """Token con el que un cliente MCP habla en nombre de esta cuenta.

    El valor es para copiar y pegar en la configuración del cliente; la app
    no lo almacena (se firma con cada emisión, ver `purplemd_auth.mcp_tokens`).
    """

    token: str
    # La cabecera exacta a mandar, para que no haya que adivinarla.
    header: str = "X-PurpleMD-Token"
    expires_at: int


@app.get("/api/auth/login", include_in_schema=False)
def login_google(request: Request, destino: str = Query(default="/")) -> RedirectResponse:
    """Redirige al consentimiento de Google con `state` y PKCE.

    El `verifier` de PKCE y el `state` viajan en una cookie firmada de
    corta vida: es lo que permite verificar en el callback que ese
    redireccionamiento lo disparó esta misma pestaña.
    """
    config = _config()
    if not config.habilitado:
        raise HTTPException(
            status_code=503,
            detail="la integración con Google no está configurada en este servidor",
        )
    verifier = nuevo_verifier()
    state = nuevo_state()
    payload = {"state": state, "verifier": verifier, "destino": _destino_seguro(destino)}
    respuesta = RedirectResponse(
        url_autorizacion(config, _redirect_uri(request, config), state, verifier),
        status_code=302,
    )
    respuesta.set_cookie(
        COOKIE_OAUTH,
        firmar(payload, config.secret_key, TTL_OAUTH_SEG),
        max_age=TTL_OAUTH_SEG,
        **cookie_segura(es_https(request)),
    )
    return respuesta


@app.get("/api/auth/callback", include_in_schema=False)
def callback_google(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Intercambia el código de Google por tokens y arma la sesión.

    Tres verificaciones antes de tocar nada: que el `state` coincida con
    el de esta pestaña (CSRF del propio flujo), que el intercambio con
    Google salga bien, y que el perfil traiga un `sub` estable. Si algo
    falla, no se crea sesión.
    """
    config = _config()
    if not config.habilitado:
        raise HTTPException(
            status_code=503,
            detail="la integración con Google no está configurada en este servidor",
        )
    if error:
        raise HTTPException(status_code=400, detail=f"Google no autorizó el acceso: {error}")

    guardado = verificar(request.cookies.get(COOKIE_OAUTH), config.secret_key)
    if guardado is None or not state:
        raise HTTPException(
            status_code=400,
            detail="la operación expiró o no coincide con esta pestaña: volvé a intentar",
        )
    if not hmac.compare_digest(str(guardado.get("state", "")), state):
        raise HTTPException(status_code=400, detail="estado de la operación inválido")
    verifier = guardado.get("verifier")
    if not isinstance(verifier, str) or not verifier:
        raise HTTPException(
            status_code=400, detail="falta el desafío PKCE de esta operación"
        )
    if not code:
        raise HTTPException(status_code=400, detail="falta el código de autorización de Google")

    redirect_uri = _redirect_uri(request, config)
    try:
        tokens = intercambiar_codigo(config, redirect_uri, code, verifier)
        cuenta_google = perfil(tokens["access_token"])
    except OAuthError as exc:
        logger.warning("falló el intercambio con Google: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    sub = cuenta_google["sub"]
    cuentas = almacen_de_entorno()
    previa = cuentas.obtener(sub)
    # Google solo entrega `refresh_token` en la primera autorización; en
    # las siguientes hay que conservar el que ya estaba guardado o la
    # sesión moriría a la hora.
    refresh = tokens.get("refresh_token") or (previa.refresh_token if previa else "")
    cuenta = Cuenta(
        sub=sub,
        email=str(cuenta_google.get("email", "")),
        name=str(cuenta_google.get("name", "")),
        picture=str(cuenta_google.get("picture", "")),
        access_token=str(tokens["access_token"]),
        refresh_token=refresh if isinstance(refresh, str) else "",
        expires_at=int(time.time()) + int(tokens.get("expires_in", 3600)),
        scope=str(tokens.get("scope", "")),
    )
    try:
        cuentas.guardar(cuenta)
    except LimiteCuentasError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    sesion = {
        "sub": sub,
        "email": cuenta.email,
        "name": cuenta.name,
        "picture": cuenta.picture,
    }
    destino = _destino_seguro(str(guardado.get("destino", "/")))
    respuesta = RedirectResponse(destino, status_code=302)
    respuesta.delete_cookie(COOKIE_OAUTH, path="/")
    respuesta.set_cookie(
        COOKIE_SESION,
        firmar(sesion, config.secret_key, TTL_SESION_SEG),
        max_age=TTL_SESION_SEG,
        **cookie_segura(es_https(request)),
    )
    return respuesta


@app.get("/api/auth/me", response_model=SesionSalida, include_in_schema=False)
def estado_de_sesion(request: Request) -> SesionSalida:
    """Dice al frontend si hay que entrar y con qué cuenta.

    Responde 200 siempre: la ausencia de sesión es un estado, no un
    error, y el frontend necesita leerlo para mostrar la pantalla de
    acceso en lugar de recibir un 401 en cada request.
    """
    config = _config()
    sesion = _sesion(request)
    return SesionSalida(
        requiere_sesion=config.habilitado,
        autenticado=sesion is not None,
        email=(sesion or {}).get("email", ""),
        name=(sesion or {}).get("name", ""),
        picture=(sesion or {}).get("picture", ""),
        almacen=os.environ.get("PURPLEMD_STORAGE", "filesystem").lower(),
    )


@app.post("/api/auth/mcp-token", response_model=TokenMcpSalida, include_in_schema=False)
def emitir_token_mcp(request: Request) -> TokenMcpSalida:
    """Emite el token MCP de la cuenta con sesión, para copiar en un cliente.

    Stateless: no hay tabla de tokens, el valor es un payload firmado con el
    `sub` de la cuenta (ver `purplemd_auth.mcp_tokens`). Cada emisión sirve
    90 días; las anteriores siguen sirviendo hasta que venzan, y rotar
    `PURPLEMD_SECRET_KEY` las vence a todas.
    """
    config = _config()
    if not config.habilitado:
        raise HTTPException(
            status_code=503,
            detail="la integración con Google no está configurada en este servidor",
        )
    sesion = _sesion(request)
    if sesion is None:
        raise HTTPException(
            status_code=401, detail="sesión requerida: iniciá sesión con Google"
        )
    ahora = time.time()
    return TokenMcpSalida(
        token=crear_token_mcp(sesion["sub"], config.secret_key, ahora),
        expires_at=int(ahora) + TTL_TOKEN_MCP_SEG,
    )


@app.post("/api/auth/logout", status_code=204, response_class=Response, include_in_schema=False)
def cerrar_sesion(request: Request) -> Response:
    """Borra la sesión del navegador **y** los tokens guardados en el servidor.

    Con eso el access token que abría el Drive del usuario deja de existir
    del lado de PurpleMD; volver a entrar repite el consentimiento.
    """
    sesion = _sesion(request)
    if sesion is not None:
        almacen_de_entorno().borrar(sesion["sub"])
    respuesta = Response(status_code=204)
    respuesta.delete_cookie(COOKIE_SESION, path="/")
    return respuesta


@app.get("/api/projects", response_model=ListadoProyectos)
def listar_proyectos(almacen: StorageDep) -> ListadoProyectos:
    """Lista los proyectos del directorio de datos, más recientes primero."""
    resumenes = [
        ProyectoSalida(name=proyecto.name, modified=proyecto.modified)
        for proyecto in purplemd.listar_proyectos(storage=almacen)
    ]
    return ListadoProyectos(projects=resumenes)


@app.post("/api/projects", response_model=ProyectoSalida, status_code=201)
def crear_proyecto(almacen: StorageDep, payload: ProyectoCreacion) -> ProyectoSalida:
    """Crea un proyecto; 409 si ya existe y 422 si el nombre no sirve."""
    proyecto = purplemd.crear_proyecto(payload.name, storage=almacen)
    return ProyectoSalida(name=proyecto.name, modified=proyecto.modified)


@app.patch("/api/projects/{project}", response_model=ProyectoSalida)
def renombrar_proyecto(
    almacen: StorageDep, project: str, payload: ProyectoRenombre
) -> ProyectoSalida:
    """Renombra un proyecto; 404, 409 si ya hay otro con ese nombre o 422.

    Renombrar al mismo nombre responde 200 con el proyecto tal cual está
    (idempotente, para que reenviar el formulario no falle).
    """
    proyecto = purplemd.renombrar_proyecto(project, payload.name, storage=almacen)
    return ProyectoSalida(name=proyecto.name, modified=proyecto.modified)


@app.delete("/api/projects/{project}", status_code=204, response_class=Response)
def eliminar_proyecto(almacen: StorageDep, project: str) -> Response:
    """Borra el proyecto con todo su contenido de forma recursiva; 404 si no existe.

    El borrado es directo y sin vuelta atrás: la confirmación la hace el
    frontend antes de llamar.
    """
    purplemd.eliminar_proyecto(project, storage=almacen)
    return Response(status_code=204)


@app.get("/api/projects/{project}/export")
def exportar_proyecto(almacen: StorageDep, project: str) -> Response:
    """Exporta el proyecto completo como ZIP; 404 si no existe."""
    zip_bytes = purplemd.exportar_proyecto(project, storage=almacen)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{project}.zip"'},
    )


@app.post("/api/projects/{project}/import")
async def importar_proyecto(
    almacen: StorageDep, project: str, file: UploadFile = File(...)
) -> dict:
    """Importa un proyecto desde ZIP; lo crea si no existe.

    413 si el archivo supera MAX_IMPORT_ZIP_BYTES y 422 si la ruta no sirve
    o el archivo no es `.zip`. Descomprimir y escribir el ZIP es trabajo
    bloqueante, así que corre en el threadpool: el event loop sigue
    atendiendo el resto de las peticiones.
    """
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=422, detail="El archivo debe ser .zip")
    # Leer MAX_IMPORT_ZIP_BYTES + 1 basta para detectar el exceso sin cargar
    # en memoria un archivo de tamaño desconocido.
    zip_bytes = await file.read(MAX_IMPORT_ZIP_BYTES + 1)
    if len(zip_bytes) > MAX_IMPORT_ZIP_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"el ZIP supera los {MAX_IMPORT_ZIP_BYTES} bytes",
        )
    return await run_in_threadpool(
        purplemd.importar_proyecto, project, zip_bytes, storage=almacen
    )


@app.get("/api/projects/{project}/tree", response_model=ArbolProyecto)
def arbol(almacen: StorageDep, project: str) -> ArbolProyecto:
    """Árbol recursivo del proyecto; 404 si no existe y 422 si el nombre no sirve."""
    resultado = purplemd.arbol_proyecto(project, storage=almacen)
    entradas = [
        EntradaArbol(type=entrada.type, path=entrada.path, modified=entrada.modified)
        for entrada in resultado.entries
    ]
    return ArbolProyecto(project=resultado.project, entries=entradas)


@app.post("/api/projects/{project}/notes", response_model=NotaSalida, status_code=201)
def crear_nota(almacen: StorageDep, project: str, payload: NotaCreacion) -> NotaSalida:
    """Crea una nota creando las carpetas que falten; 404, 409 o 422."""
    return _salida(purplemd.crear_nota(project, payload.path, payload.content, storage=almacen))


@app.get("/api/projects/{project}/notes/{path:path}/pdf")
def exportar_pdf(
    almacen: StorageDep,
    project: str,
    path: str,
) -> Response:
    """Devuelve la nota como PDF con marca de agua "Generado con PurpleMD ♥".
    La marca de agua siempre se incluye. No hay parámetro para omitirla.
    """
    nota = purplemd.leer_nota(project, path, storage=almacen)
    html = _html_para_pdf(nota)
    pdf = weasyprint.HTML(string=html, url_fetcher=FETCHER_PDF).write_pdf()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nota.path}.pdf"'},
    )


@app.get("/api/projects/{project}/notes/{path:path}", response_model=NotaSalida)
def leer(almacen: StorageDep, project: str, path: str) -> NotaSalida:
    """Devuelve una nota con su contenido; 404 si no existe y 422 si la ruta no sirve."""
    return _salida(purplemd.leer_nota(project, path, storage=almacen))


@app.put("/api/projects/{project}/notes/{path:path}", response_model=NotaSalida)
def guardar(
    almacen: StorageDep, project: str, path: str, payload: ActualizacionNota
) -> NotaSalida:
    """Reemplaza el contenido de una nota; 404 si no existe y 422 si es muy grande o binario."""
    return _salida(purplemd.guardar_nota(project, path, payload.content, storage=almacen))


@app.patch("/api/projects/{project}/notes/{path:path}", response_model=NotaSalida)
def mover_nota(
    almacen: StorageDep, project: str, path: str, payload: RutaNueva
) -> NotaSalida:
    """Mueve o renombra una nota dentro del proyecto; 404, 409 destino ocupado o 422.

    La respuesta trae la ruta nueva: si el frontend tenía esa nota abierta,
    es su problema de estado, no del backend.
    """
    return _salida(purplemd.mover_nota(project, path, payload.path, storage=almacen))


@app.delete(
    "/api/projects/{project}/notes/{path:path}", status_code=204, response_class=Response
)
def eliminar_nota(almacen: StorageDep, project: str, path: str) -> Response:
    """Borra la nota; 404 si no existe (el proyecto o la ruta) y 422 si la ruta no sirve."""
    purplemd.eliminar_nota(project, path, storage=almacen)
    return Response(status_code=204)


@app.patch("/api/projects/{project}/dirs/{path:path}", response_model=DirectorioSalida)
def mover_directorio(
    almacen: StorageDep, project: str, path: str, payload: RutaNueva
) -> DirectorioSalida:
    """Mueve o renombra un directorio con su contenido; 404, 409 o 422.

    422 si la ruta destino no sirve o si el directorio terminaría dentro de
    sí mismo o de un ancestro propio. Mover a la misma ruta es 200.
    """
    directorio = purplemd.mover_directorio(project, path, payload.path, storage=almacen)
    return DirectorioSalida(
        project=directorio.project, path=directorio.path, modified=directorio.modified
    )


@app.delete(
    "/api/projects/{project}/dirs/{path:path}", status_code=204, response_class=Response
)
def eliminar_directorio(
    almacen: StorageDep,
    project: str,
    path: str,
    recursive: Annotated[
        bool,
        Query(description="Borra el directorio con todo su contenido aunque no esté vacío"),
    ] = False,
) -> Response:
    """Borra un directorio; 404 si no existe y 409 si no está vacío y no se pidió recursive."""
    purplemd.eliminar_directorio(project, path, recursive=recursive, storage=almacen)
    return Response(status_code=204)


@app.post("/api/render", response_model=RenderResponse)
def render(payload: RenderRequest) -> RenderResponse:
    """Convierte markdown en HTML para la vista previa; 422 si pasa 200 KB."""
    return RenderResponse(html=renderer.renderizar(payload.markdown))


@app.post("/api/pdf")
def exportar_pdf_stateless(payload: PdfRequest) -> Response:
    """Convierte markdown en PDF; el PDF del modo invitado.

    No existe un equivalente con storage: en modo invitado no hay cuenta
    y por tanto no hay dónde leer la nota, así que el frontend le manda
    el markdown crudo. Como `/api/render`, no lee ni escribe nada, que es
    por lo que los dos pasan sin sesión (ver `_seguridad_y_sesion`); su
    tope de MAX_RENDER_BYTES lo aplica `RenderRequest`, del que hereda.
    """
    html = _html_de_markdown(payload.markdown, payload.nombre)
    pdf = weasyprint.HTML(string=html, url_fetcher=FETCHER_PDF).write_pdf()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{payload.nombre}.pdf"'
        },
    )


def _html_para_pdf(nota: purplemd.Nota) -> str:
    """Envuelve la nota en un documento PDF completo con estilos.

    Atajo para el PDF con storage; el cuerpo vive en `_html_de_markdown`,
    que comparten con el PDF stateless del modo invitado.
    """
    return _html_de_markdown(nota.content, nota.path)


def _html_de_markdown(markdown: str, titulo: str) -> str:
    """Documento WeasyPrint a partir de markdown crudo.

    WeasyPrint necesita un HTML con `<style>` propio para aplicar márgenes,
    tipografía y los colores del resaltado de sintaxis.
    Estilo profesional inspirado en CVs generados por Claude.

    `titulo` va al `<title>` y al nombre del archivo. Quien llama es el
    que garantiza que es un nombre válido (sin `<`, comillas ni saltos de
    línea): acá se usa tal cual, como ya hacía el PDF con storage.

    La marca de agua "Generado con PurpleMD ♥" siempre se incluye en @bottom-left.
    El número de página @bottom-right es paginación del documento y se emite siempre.
    """
    cuerpo = renderer.renderizar(markdown)
    # Paleta del resaltado y fondo de los bloques de código: los dos salen
    # de Pygments (vía renderer) en vez de estar escritos como literales en
    # este CSS, así la paleta del PDF es la por defecto del resaltador.
    paleta = renderer.css_resaltado()
    fondo = renderer.fondo_resaltado()
    # La marca de agua siempre se incluye en @bottom-left.
    # `\\2665`: la barra va doble porque el literal es de Python; con una
    # sola, Python lo lee como escape octal (`¶5`) y el pie no imprime ♥.
    marca = """      /* Marca de agua a la izquierda con el corazón Unicode \\2665 */
      @bottom-left {
        content: "Generado con PurpleMD \\2665";
        font-family: "DejaVu Sans", "Liberation Sans", sans-serif;
        font-size: 6.5pt;
        font-weight: 600;
        color: var(--accent);
      }

"""
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{titulo}</title>

  <style>
    @page {{
      size: A4;
      margin: 1.35cm 1.45cm 1.25cm 1.45cm;

{marca}      /* Número de página a la derecha */
      @bottom-right {{
        content: "Pág. " counter(page);
        font-family: "DejaVu Sans", "Liberation Sans", sans-serif;
        font-size: 6.5pt;
        color: #7b8491;
      }}
    }}


    :root {{
        --text: #1b2430;
        --muted: #5e6875;
        --accent: #483096;
        --line: #483096;
        --soft: #f3f6fa;
    }}
    * {{
      box-sizing: border-box;
    }}

    html,
    body {{
      margin: 0;
      padding: 0;
    }}

    /* Cadenas de fuentes del PDF: NUNCA meter "Noto Color Emoji" aquí. En
       Debian, 45-generic.conf/60-generic.conf promueven esa familia por
       encima de DejaVu Sans en fontconfig y, como la emoji tiene glifos
       0-9, todos los números del documento salen en tipografía de emoji.
       Los emoji (💜, ☰…) siguen resolviendo igual por fallback. */

    body {{
      color: var(--text);
      font-family: "DejaVu Sans", "Liberation Sans", sans-serif;
      font-size: 8.5pt;
      line-height: 1.38;
      max-width: none;
    }}

    /* Encabezado principal del documento */

    body > h1:first-child {{
      margin: 0 0 0.12em;
      padding: 0;
      border: none;
      color: var(--text);
      font-family: "DejaVu Sans", "Liberation Sans", sans-serif;
      font-size: 22pt;
      font-weight: 700;
      letter-spacing: -0.4px;
      line-height: 1.05;
    }}

    body > h1:first-child + p {{
      margin: 0 0 0.9em;
      color: var(--accent);
      font-family: "DejaVu Sans", "Liberation Sans", sans-serif;
      font-size: 10pt;
      font-weight: 600;
      line-height: 1.35;
    }}

    /* Texto general */

    p {{
      margin: 0 0 0.55em;
      text-align: left;
    }}

    a {{
      color: var(--accent);
      text-decoration: none;
    }}

    a:hover {{
      text-decoration: underline;
    }}

    strong {{
      font-weight: 700;
    }}

    em {{
      color: var(--muted);
    }}

    /* Títulos de sección */

    h1,
    h2,
    h3,
    h4,
    h5,
    h6 {{
      break-after: avoid;
      color: var(--text);
      font-family: "DejaVu Sans", "Liberation Sans", sans-serif;
      font-weight: 700;
      line-height: 1.2;
    }}

    h1 {{
      margin: 1.1em 0 0.35em;
      font-size: 11pt;
    }}

    h2 {{
      display: flex;
      align-items: center;
      gap: 0.7em;
      margin: 1.05em 0 0.45em;
      padding-bottom: 0.22em;
      border-bottom: 1px solid var(--line);
      color: var(--accent);
      font-size: 9.5pt;
      font-weight: 750;
      letter-spacing: 0.55px;
      text-transform: uppercase;
    }}

    h3 {{
      margin: 0.75em 0 0.15em;
      color: var(--accent);
      font-size: 9.2pt;
    }}

    h4 {{
      margin: 0.65em 0 0.15em;
      color: var(--accent);
      font-size: 8.8pt;
    }}

    /* Primer bloque de contenido */

    body > *:first-child {{
      margin-top: 0;
    }}

    /* Listas */

    ul,
    ol {{
      margin: 0.25em 0 0.65em;
      padding-left: 1.35em;
    }}

    li {{
      margin: 0 0 0.25em;
      padding-left: 0.15em;
      color: #354252;
    }}

    li::marker {{
      color: var(--accent);
    }}

    li > ul,
    li > ol {{
      margin-top: 0.18em;
      margin-bottom: 0.2em;
    }}

    /* Separadores */

    hr {{
      margin: 1em 0;
      border: none;
      border-top: 1px solid var(--line);
    }}

    /* Código inline */

    code {{
      padding: 0.08em 0.28em;
      border-radius: 2px;
      background: #eef1f5;
      color: #26364d;
      font-family: "DejaVu Sans Mono", Consolas, monospace;
      font-size: 0.82em;
    }}

    /* Resaltado de sintaxis: la paleta por defecto de Pygments, generada
       por renderer.css_resaltado() y no escrita a mano en este archivo.
       Va antes que las reglas estructurales de abajo para que la que
       Pygments emite para `pre` no pise el line-height del bloque. */

{paleta}
    /* Bloques de código: fuente monoespaciada y saltos de línea intactos.
       El resaltado cambia `<pre><code>` por un `<div class="highlight">`,
       que sin estas reglas caía en la fuente del documento y juntaba todo
       el código en un solo renglón.
       `white-space: pre-wrap` en vez de `pre`: el PDF no tiene scroll, así
       que una línea larga se envuelve antes que quedar cortada. */

    pre,
    .highlight {{
      margin: 0.65em 0;
      padding: 0.75rem;
      border: none;
      border-radius: 4px;
      background: {fondo};
      font-family: "DejaVu Sans Mono", Consolas, monospace;
      font-size: 6.8pt;
      line-height: 1.4;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      break-inside: avoid;
    }}

    pre code {{
      padding: 0;
      background: transparent;
      color: inherit;
      font-family: inherit;
      font-size: inherit;
      line-height: inherit;
    }}

    /* Citas */

    blockquote {{
      margin: 0.8em 0;
      padding: 0.55em 0.85em;
      border-left: 3px solid var(--accent);
      border-radius: 0 3px 3px 0;
      background: var(--soft);
      color: var(--muted);
      font-style: italic;
    }}

    blockquote p {{
      margin: 0;
    }}

    /* Tablas */

    table {{
      width: 100%;
      margin: 0.75em 0;
      border-collapse: collapse;
      font-size: 8pt;
      break-inside: avoid;
    }}

    th,
    td {{
      padding: 0.35rem 0.45rem;
      border: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}

    th {{
      background: var(--soft);
      color: var(--text);
      font-weight: 700;
    }}

    tr:nth-child(even) td {{
      background: #fafbfd;
    }}

    /* Imágenes */

    img {{
      display: block;
      max-width: 100%;
      height: auto;
      margin: 0.6em auto;
      border-radius: 3px;
    }}

    /* Casillas de tareas: en línea con su texto, no en un renglón solo.
       WeasyPrint las baja a su propia línea y el texto queda colgando. */

    input[type="checkbox"] {{
      display: inline-block;
      margin-right: 0.35em;
      accent-color: var(--accent);
    }}

    /* Control de saltos para PDF */

    h1,
    h2,
    h3,
    h4,
    h5,
    h6,
    table,
    blockquote,
    pre,
    .highlight {{
      break-inside: avoid;
    }}

    p,
    ul,
    ol {{
      orphans: 3;
      widows: 3;
    }}
  </style>
</head>

<body>
{cuerpo}
</body>
</html>"""

# --- Notificaciones ---
# Sistema de avisos en la interfaz: el backend guarda notificaciones en
# memoria y el frontend las muestra como toast al cargar. Sirve para pedir
# aprobación o avisar tareas sin tener que mirar la terminal.


@dataclass
class Notificacion:
    id: str
    titulo: str
    mensaje: str
    leida: bool = False


_notificaciones: list[Notificacion] = []
_contador = 0


def _nueva_notificacion(titulo: str, mensaje: str) -> Notificacion:
    global _contador
    _contador += 1
    notif = Notificacion(id=str(_contador), titulo=titulo, mensaje=mensaje)
    _notificaciones.append(notif)
    return notif


class NotificacionCreacion(BaseModel):
    """Cuerpo para crear una notificación."""

    titulo: str
    mensaje: str


@app.get("/api/notifications")
def listar_notificaciones() -> dict:
    """Devuelve las notificaciones pendientes (no leídas)."""
    return {
        "notifications": [
            {"id": n.id, "titulo": n.titulo, "mensaje": n.mensaje}
            for n in _notificaciones
            if not n.leida
        ]
    }


@app.post("/api/notifications", response_model=dict, status_code=201)
def crear_notificacion(payload: NotificacionCreacion) -> dict:
    """Crea una notificación. Lo usa el frontend y el MCP (futuro)."""
    notif = _nueva_notificacion(payload.titulo, payload.mensaje)
    return {"id": notif.id, "titulo": notif.titulo, "mensaje": notif.mensaje}


@app.post("/api/notifications/{notif_id}/read", status_code=204)
def marcar_leida(notif_id: str) -> Response:
    """Marca una notificación como leída."""
    for n in _notificaciones:
        if n.id == notif_id:
            n.leida = True
            break
    return Response(status_code=204)


# Notificación de bienvenida: se crea al importar el módulo para que el
# servidor la tenga en memoria cuando arranca. Sirve para avisar que el
# sistema de notificaciones está activo.
_nueva_notificacion(
    "Notificaciones activas",
    "El sistema de notificaciones está funcionando. Vas a ver los acá los avisos.",
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Reporta si se puede persistir; responde 200 con el estado en el body.

    `/health` lo consulta el HEALTHCHECK del contenedor cada pocos
    segundos, así que **no** hace una llamada a Drive: con
    `PURPLEMD_STORAGE=drive` juzga la configuración, que es lo que sin
    esa variable ya se resolvía con `esta_operativo()`.
    """
    backend = os.environ.get("PURPLEMD_STORAGE", "filesystem").lower()
    if backend == "drive":
        return HealthResponse(estado="ok" if _config().habilitado else "degradado")
    try:
        almacen = get_storage()
    except ValueError as exc:
        logger.error("PURPLEMD_STORAGE inválido: %s", exc)
        return HealthResponse(estado="degradado")
    return HealthResponse(estado="ok" if almacen.esta_operativo() else "degradado")


@app.get("/privacy", include_in_schema=False)
def privacy() -> FileResponse:
    """Política de Privacidad."""
    return FileResponse(
        Path(__file__).parent / "static" / "privacy.html",
        media_type="text/html",
    )


@app.get("/terms", include_in_schema=False)
def terms() -> FileResponse:
    """Condiciones del Servicio."""
    return FileResponse(
        Path(__file__).parent / "static" / "terms.html",
        media_type="text/html",
    )
