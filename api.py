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

import os  # noqa: F401 (usado en tests para patch)
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import weasyprint
from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, field_validator

import purplemd
import renderer
from purplemd_storage import get_storage

# Tope de markdown para POST /api/render. El HTML renderizado puede pesar
# varios veces más que la entrada, y el parseo corre en el hilo del request:
# 200 KB bastan para cualquier nota real y evitan requests que cuelen el
# evento durante segundos.
MAX_RENDER_BYTES = 200 * 1024

# Página del frontend servida en GET /. Se resuelve relativa a este archivo
# y no al cwd para que funcione igual desde cualquier directorio.
INDEX_HTML = Path(__file__).parent / "static" / "index.html"

# Instancia global de storage: se crea al importar y se reusa en todos los
# endpoints. `get_storage()` lee PURPLEMD_STORAGE en cada llamada, así que
# cambios en la variable de entorno surten efecto en caliente (útil en tests).
_storage = get_storage()

app = FastAPI(
    title="purplemd",
    description=(
        "Editor de markdown ligero: notas en proyectos con subcarpetas y vista previa en HTML."
    ),
)

# CORS: permite acceder desde http://localhost:8000 (mismo puerto, host distinto
# para el navegador) además de http://127.0.0.1:8000.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Montado como ruta (y no como router) para que /static/css/style.css y
# /static/js/app.js se sirvan sin escribir endpoints a mano.
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


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
    """Último recurso: 500 genérico, sin exponer el stack trace ni datos internos."""
    return _respuesta_error(500, "error interno al procesar la solicitud")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Sirve el frontend (index.html) tal cual está en disco.

    No aparece en /docs porque es solo el frontend, no un endpoint de datos.
    """
    return FileResponse(INDEX_HTML, media_type="text/html")


@app.get("/api/projects", response_model=ListadoProyectos)
def listar_proyectos() -> ListadoProyectos:
    """Lista los proyectos del directorio de datos, más recientes primero."""
    resumenes = [
        ProyectoSalida(name=proyecto.name, modified=proyecto.modified)
        for proyecto in purplemd.listar_proyectos(storage=_storage)
    ]
    return ListadoProyectos(projects=resumenes)


@app.post("/api/projects", response_model=ProyectoSalida, status_code=201)
def crear_proyecto(payload: ProyectoCreacion) -> ProyectoSalida:
    """Crea un proyecto; 409 si ya existe y 422 si el nombre no sirve."""
    proyecto = purplemd.crear_proyecto(payload.name, storage=_storage)
    return ProyectoSalida(name=proyecto.name, modified=proyecto.modified)


@app.patch("/api/projects/{project}", response_model=ProyectoSalida)
def renombrar_proyecto(project: str, payload: ProyectoRenombre) -> ProyectoSalida:
    """Renombra un proyecto; 404, 409 si ya hay otro con ese nombre o 422.

    Renombrar al mismo nombre responde 200 con el proyecto tal cual está
    (idempotente, para que reenviar el formulario no falle).
    """
    proyecto = purplemd.renombrar_proyecto(project, payload.name, storage=_storage)
    return ProyectoSalida(name=proyecto.name, modified=proyecto.modified)


@app.delete("/api/projects/{project}", status_code=204, response_class=Response)
def eliminar_proyecto(project: str) -> Response:
    """Borra el proyecto con todo su contenido de forma recursiva; 404 si no existe.

    El borrado es directo y sin vuelta atrás: la confirmación la hace el
    frontend antes de llamar.
    """
    purplemd.eliminar_proyecto(project, storage=_storage)
    return Response(status_code=204)


@app.get("/api/projects/{project}/export")
def exportar_proyecto(project: str) -> Response:
    """Exporta el proyecto completo como ZIP; 404 si no existe."""
    zip_bytes = purplemd.exportar_proyecto(project, storage=_storage)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{project}.zip"'},
    )


@app.post("/api/projects/{project}/import")
async def importar_proyecto(project: str, file: UploadFile = File(...)) -> dict:
    """Importa un proyecto desde ZIP; 404 si no existe, 422 si el ZIP es inválido."""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=422, detail="El archivo debe ser .zip")
    zip_bytes = await file.read()
    resultado = purplemd.importar_proyecto(project, zip_bytes, storage=_storage)
    return resultado


@app.get("/api/projects/{project}/tree", response_model=ArbolProyecto)
def arbol(project: str) -> ArbolProyecto:
    """Árbol recursivo del proyecto; 404 si no existe y 422 si el nombre no sirve."""
    resultado = purplemd.arbol_proyecto(project, storage=_storage)
    entradas = [
        EntradaArbol(type=entrada.type, path=entrada.path, modified=entrada.modified)
        for entrada in resultado.entries
    ]
    return ArbolProyecto(project=resultado.project, entries=entradas)


@app.post("/api/projects/{project}/notes", response_model=NotaSalida, status_code=201)
def crear_nota(project: str, payload: NotaCreacion) -> NotaSalida:
    """Crea una nota creando las carpetas que falten; 404, 409 o 422."""
    return _salida(purplemd.crear_nota(project, payload.path, payload.content, storage=_storage))


@app.get("/api/projects/{project}/notes/{path:path}/pdf")
def exportar_pdf(
    project: str,
    path: str,
    sin_marca: bool = Query(
        False,
        description="Omite el pie «Generado con PurpleMD ♥» del PDF.",
    ),
) -> Response:
    """Devuelve la nota como PDF; 404 si no existe, 422 si la ruta no sirve.

    `sin_marca=1` deja fuera la marca de agua del pie. Es una preferencia
    de quien exporta, no una protección: sin autenticación no hay sello
    que valga, así que el parámetro se acepta siempre.
    """
    nota = purplemd.leer_nota(project, path, storage=_storage)
    html = _html_para_pdf(nota, sin_marca=sin_marca)
    pdf = weasyprint.HTML(string=html).write_pdf()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nota.path}.pdf"'},
    )


@app.get("/api/projects/{project}/notes/{path:path}", response_model=NotaSalida)
def leer(project: str, path: str) -> NotaSalida:
    """Devuelve una nota con su contenido; 404 si no existe y 422 si la ruta no sirve."""
    return _salida(purplemd.leer_nota(project, path, storage=_storage))


@app.put("/api/projects/{project}/notes/{path:path}", response_model=NotaSalida)
def guardar(project: str, path: str, payload: ActualizacionNota) -> NotaSalida:
    """Reemplaza el contenido de una nota; 404 si no existe y 422 si es muy grande o binario."""
    return _salida(purplemd.guardar_nota(project, path, payload.content, storage=_storage))


@app.patch("/api/projects/{project}/notes/{path:path}", response_model=NotaSalida)
def mover_nota(project: str, path: str, payload: RutaNueva) -> NotaSalida:
    """Mueve o renombra una nota dentro del proyecto; 404, 409 destino ocupado o 422.

    La respuesta trae la ruta nueva: si el frontend tenía esa nota abierta,
    es su problema de estado, no del backend.
    """
    return _salida(purplemd.mover_nota(project, path, payload.path, storage=_storage))


@app.delete(
    "/api/projects/{project}/notes/{path:path}", status_code=204, response_class=Response
)
def eliminar_nota(project: str, path: str) -> Response:
    """Borra la nota; 404 si no existe (el proyecto o la ruta) y 422 si la ruta no sirve."""
    purplemd.eliminar_nota(project, path, storage=_storage)
    return Response(status_code=204)


@app.patch("/api/projects/{project}/dirs/{path:path}", response_model=DirectorioSalida)
def mover_directorio(project: str, path: str, payload: RutaNueva) -> DirectorioSalida:
    """Mueve o renombra un directorio con su contenido; 404, 409 o 422.

    422 si la ruta destino no sirve o si el directorio terminaría dentro de
    sí mismo o de un ancestro propio. Mover a la misma ruta es 200.
    """
    directorio = purplemd.mover_directorio(project, path, payload.path, storage=_storage)
    return DirectorioSalida(
        project=directorio.project, path=directorio.path, modified=directorio.modified
    )


@app.delete(
    "/api/projects/{project}/dirs/{path:path}", status_code=204, response_class=Response
)
def eliminar_directorio(
    project: str,
    path: str,
    recursive: Annotated[
        bool,
        Query(description="Borra el directorio con todo su contenido aunque no esté vacío"),
    ] = False,
) -> Response:
    """Borra un directorio; 404 si no existe y 409 si no está vacío y no se pidió recursive."""
    purplemd.eliminar_directorio(project, path, recursive=recursive, storage=_storage)
    return Response(status_code=204)


@app.post("/api/render", response_model=RenderResponse)
def render(payload: RenderRequest) -> RenderResponse:
    """Convierte markdown en HTML para la vista previa; 422 si pasa 200 KB."""
    return RenderResponse(html=renderer.renderizar(payload.markdown))


def _html_para_pdf(nota: purplemd.Nota, sin_marca: bool = False) -> str:
    """Envuelve el HTML renderizado en un documento completo con estilos.

    WeasyPrint necesita un HTML con `<style>` propio para aplicar márgenes,
    tipografía y los colores del resaltado de sintaxis.
    Estilo profesional inspirado en CVs generados por Claude.

    Con `sin_marca` se omite el pie `@bottom-left` («Generado con
    PurpleMD ♥»). El número de página `@bottom-right` es paginación del
    documento y se emite siempre.
    """
    cuerpo = renderer.renderizar(nota.content)
    # El pie de la marca va en una variable para poder omitirlo sin
    # duplicar el f-string: sus llaves literales entran por interpolación
    # y no necesitan escape. Con `sin_marca` queda vacío.
    marca = (
        ""
        if sin_marca
        else """      /* Marca de agua a la izquierda con el corazón Unicode \2665 */
      @bottom-left {
        content: "Generado con PurpleMD \\2665";
        font-family: "DejaVu Sans", Arial, sans-serif;
        font-size: 6.5pt;
        font-weight: 600;
        color: var(--accent);
      }

"""
    )
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{nota.path}</title>

  <style>
    @page {{
      size: A4;
      margin: 1.35cm 1.45cm 1.25cm 1.45cm;

{marca}      /* Número de página a la derecha */
      @bottom-right {{
        content: "Pág. " counter(page);
        font-family: "DejaVu Sans", Arial, sans-serif;
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
        --code: #20242b;
    }}
    * {{
      box-sizing: border-box;
    }}

    html,
    body {{
      margin: 0;
      padding: 0;
    }}

    body {{
      color: var(--text);
      font-family: "DejaVu Sans", Arial, sans-serif;
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
      font-family: "DejaVu Sans", Arial, sans-serif;
      font-size: 22pt;
      font-weight: 700;
      letter-spacing: -0.4px;
      line-height: 1.05;
    }}

    body > h1:first-child + p {{
      margin: 0 0 0.9em;
      color: var(--accent);
      font-family: "DejaVu Sans", Arial, sans-serif;
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
      font-family: "DejaVu Sans", Arial, sans-serif;
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

    /* Bloques de código */

    pre {{
      overflow-x: auto;
      margin: 0.65em 0;
      padding: 0.75rem;
      border: none;
      border-radius: 4px;
      background: var(--code);
      break-inside: avoid;
    }}

    pre code {{
      padding: 0;
      background: transparent;
      color: #e6edf3;
      font-family: "DejaVu Sans Mono", Consolas, monospace;
      font-size: 6.8pt;
      line-height: 1.4;
    }}

    /* Resaltado de sintaxis */

    .highlight {{
      overflow-x: auto;
      margin: 0.65em 0;
      padding: 0.75rem;
      border-radius: 4px;
      background: var(--code);
      break-inside: avoid;
    }}

    .highlight code {{
      padding: 0;
      background: transparent;
      color: #e6edf3;
    }}

    .highlight .hll {{ background-color: #3b4252; }}
    .highlight .c {{ color: #718096; font-style: italic; }}
    .highlight .err {{ color: #ff6b6b; }}
    .highlight .k {{ color: #ff79c6; }}
    .highlight .l {{ color: #f8f8f2; }}
    .highlight .n {{ color: #f8f8f2; }}
    .highlight .o {{ color: #ff79c6; }}
    .highlight .p {{ color: #f8f8f2; }}
    .highlight .cm {{ color: #718096; font-style: italic; }}
    .highlight .cp {{ color: #ff79c6; }}
    .highlight .c1 {{ color: #718096; font-style: italic; }}
    .highlight .cs {{ color: #718096; font-style: italic; }}
    .highlight .gd {{ color: #ff5555; }}
    .highlight .ge {{ color: #f8f8f2; text-decoration: underline; }}
    .highlight .gh {{ color: #f8f8f2; font-weight: bold; }}
    .highlight .gi {{ color: #50fa7b; }}
    .highlight .gp {{ color: #f8f8f2; }}
    .highlight .gs {{ color: #f8f8f2; }}
    .highlight .gu {{ color: #f8f8f2; font-weight: bold; }}
    .highlight .kc {{ color: #ff79c6; }}
    .highlight .kd {{ color: #8be9fd; font-style: italic; }}
    .highlight .kn {{ color: #ff79c6; }}
    .highlight .kp {{ color: #ff79c6; }}
    .highlight .kr {{ color: #ff79c6; }}
    .highlight .kt {{ color: #8be9fd; }}
    .highlight .m {{ color: #bd93f9; }}
    .highlight .s {{ color: #f1fa8c; }}
    .highlight .na {{ color: #50fa7b; }}
    .highlight .nb {{ color: #8be9fd; }}
    .highlight .nc {{ color: #50fa7b; }}
    .highlight .nf {{ color: #50fa7b; }}
    .highlight .nt {{ color: #ff79c6; }}
    .highlight .nv {{ color: #8be9fd; }}
    .highlight .ow {{ color: #ff79c6; }}
    .highlight .mb {{ color: #bd93f9; }}
    .highlight .mf {{ color: #bd93f9; }}
    .highlight .mi {{ color: #bd93f9; }}
    .highlight .mo {{ color: #bd93f9; }}
    .highlight .sa {{ color: #f1fa8c; }}
    .highlight .sb {{ color: #f1fa8c; }}
    .highlight .sc {{ color: #f1fa8c; }}
    .highlight .sd {{ color: #f1fa8c; }}
    .highlight .s2 {{ color: #f1fa8c; }}
    .highlight .se {{ color: #f1fa8c; }}
    .highlight .sh {{ color: #f1fa8c; }}
    .highlight .si {{ color: #f1fa8c; }}
    .highlight .sx {{ color: #f1fa8c; }}
    .highlight .s1 {{ color: #f1fa8c; }}
    .highlight .ss {{ color: #f1fa8c; }}
    .highlight .vc {{ color: #8be9fd; font-style: italic; }}
    .highlight .vg {{ color: #8be9fd; font-style: italic; }}
    .highlight .vi {{ color: #8be9fd; font-style: italic; }}
    .highlight .vm {{ color: #8be9fd; font-style: italic; }}
    .highlight .il {{ color: #bd93f9; }}

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

    /* Casillas de tareas */

    input[type="checkbox"] {{
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
    """Reporta si se puede persistir; responde 200 con el estado en el body."""
    return HealthResponse(estado="ok" if _storage.esta_operativo() else "degradado")
